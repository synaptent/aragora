/**
 * Auto-generated Aragora API client
 * DO NOT EDIT - regenerate with: npm run generate:sdk
 */

/* eslint-disable @typescript-eslint/no-unused-vars */
import { API_BASE_URL } from '@/config';
import type * as Types from './types';
import type {
  // Debate types
  DebateSummary,
  DebateCreateRequest,
  DebateCreateResponse,
  Debate,
  Round,
  Message,
  Critique,
  ImpasseAnalysis,
  ConvergenceStatus,
  Citations,
  ConsensusStats,
  SimilarDebate,
  SettledTopic,
  Dissent,
  // Agent types
  AgentProfile,
  AgentComparison,
  LeaderboardEntry,
  Match,
  MatchHistoryEntry,
  ConsistencyScore,
  RelationshipNetwork,
  PositionFlip,
  AgentRecommendation,
  // Memory types
  Memory,
  TierStats,
  // Tournament types
  Tournament,
  TournamentStandings,
  // Replay types
  Replay,
  ReplaySummary,
  // Document types
  Document,
  DocumentSummary,
  SupportedFormats,
  // Health types
  DetailedHealth,
  NomicState,
  NomicHealth,
  Mode,
  // Verification types
  VerificationStatus,
  VerificationResult,
  // Stats types
  DisagreementStats,
  RankingStats,
  RelationshipSummary,
  RelationshipGraph,
  Relationship,
  MomentsSummary,
  Moment,
  DashboardMetrics,
  TrendingTopic,
  SchedulerStatus,
  ScheduledDebateRecord,
  // Probe/Evolution types
  ProbeReport,
  EmergentTrait,
  CrossPollinationSuggestion,
  Insight,
  TeamCombination,
  EvolutionPattern,
  EvolutionEvent,
} from './types';

// Re-export types for convenience
export type { Types };

export interface ApiClientConfig {
  baseUrl: string;
  getAuthToken?: () => string | null;
  onError?: (error: Error) => void;
}

export interface RequestOptions {
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export class AragoraApiClient {
  private config: ApiClientConfig;

  constructor(config: ApiClientConfig) {
    this.config = config;
  }

  private async request<T>(
    method: string,
    path: string,
    options: RequestOptions & {
      body?: unknown;
      query?: Record<string, string | number | undefined>;
    } = {},
  ): Promise<T> {
    let url = `${this.config.baseUrl}${path}`;

    // Add query params
    if (options.query) {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(options.query)) {
        if (value !== undefined) {
          params.append(key, String(value));
        }
      }
      const queryString = params.toString();
      if (queryString) {
        url += `?${queryString}`;
      }
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    // Add auth token if available
    const token = this.config.getAuthToken?.();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      method,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });

    if (!response.ok) {
      const error = new Error(`API error: ${response.status} ${response.statusText}`);
      this.config.onError?.(error);
      throw error;
    }

    return response.json();
  }

  /**
   * List all debates
   * Returns a paginated list of recent debates
   * @requires Authentication
   */
  async getDebates(
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ debates?: DebateSummary[] }> {
    return this.request<{ debates?: DebateSummary[] }>('GET', `/api/debates`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Create a new debate
   * Starts an ad-hoc debate with the provided task/question.
   * @requires Authentication
   */
  async postDebates(
    body: DebateCreateRequest,
    options?: RequestOptions,
  ): Promise<DebateCreateResponse> {
    return this.request<DebateCreateResponse>('POST', `/api/debates`, { ...options, body });
  }

  /**
   * Create a new debate (DEPRECATED)
   * **DEPRECATED**: This endpoint will be removed on 2026-08-01.
Use POST /api/debates instead.

   * @requires Authentication
   */
  async postDebate(
    body: DebateCreateRequest,
    options?: RequestOptions,
  ): Promise<DebateCreateResponse> {
    return this.request<DebateCreateResponse>('POST', `/api/debate`, { ...options, body });
  }

  /**
   * Get debate by slug
   */
  async getDebatesSlugByslug(slug: string, options?: RequestOptions): Promise<Debate> {
    return this.request<Debate>('GET', `/api/debates/slug/${slug}`, { ...options });
  }

  /**
   * Export debate
   * @requires Authentication
   */
  async getDebatesByidExportByformat(
    id: string,
    format: 'json' | 'csv' | 'html',
    query?: { table?: 'summary' | 'messages' | 'critiques' | 'votes' },
    options?: RequestOptions,
  ): Promise<unknown> {
    return this.request<unknown>('GET', `/api/debates/${id}/export/${format}`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Detect debate impasse
   * Analyzes debate for signs of stalemate or circular arguments
   */
  async getDebatesByidImpasse(id: string, options?: RequestOptions): Promise<ImpasseAnalysis> {
    return this.request<ImpasseAnalysis>('GET', `/api/debates/${id}/impasse`, { ...options });
  }

  /**
   * Get convergence status
   */
  async getDebatesByidConvergence(
    id: string,
    options?: RequestOptions,
  ): Promise<ConvergenceStatus> {
    return this.request<ConvergenceStatus>('GET', `/api/debates/${id}/convergence`, { ...options });
  }

  /**
   * Get evidence citations
   * @requires Authentication
   */
  async getDebatesByidCitations(id: string, options?: RequestOptions): Promise<Citations> {
    return this.request<Citations>('GET', `/api/debates/${id}/citations`, { ...options });
  }

  /**
   * Fork debate at branch point
   * Create a counterfactual fork of the debate
   * @requires Authentication
   */
  async postDebatesByidFork(
    id: string,
    body: {
      /** Round number to fork from */
      branch_point: number;
      /** Optional modified context for the fork */
      modified_context?: string;
    },
    options?: RequestOptions,
  ): Promise<unknown> {
    return this.request<unknown>('POST', `/api/debates/${id}/fork`, { ...options, body });
  }

  /**
   * Get agent rankings
   */
  async getLeaderboard(
    query?: { limit?: number; domain?: string },
    options?: RequestOptions,
  ): Promise<{ leaderboard?: LeaderboardEntry[] }> {
    return this.request<{ leaderboard?: LeaderboardEntry[] }>('GET', `/api/leaderboard`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get recent matches
   */
  async getMatchesRecent(
    query?: { limit?: number; loop_id?: string },
    options?: RequestOptions,
  ): Promise<{ matches?: Match[] }> {
    return this.request<{ matches?: Match[] }>('GET', `/api/matches/recent`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get agent profile
   */
  async getAgentBynameProfile(name: string, options?: RequestOptions): Promise<AgentProfile> {
    return this.request<AgentProfile>('GET', `/api/agent/${name}/profile`, { ...options });
  }

  /**
   * Get agent match history
   */
  async getAgentBynameHistory(
    name: string,
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ history?: MatchHistoryEntry[] }> {
    return this.request<{ history?: MatchHistoryEntry[] }>('GET', `/api/agent/${name}/history`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get consistency score
   */
  async getAgentBynameConsistency(
    name: string,
    options?: RequestOptions,
  ): Promise<ConsistencyScore> {
    return this.request<ConsistencyScore>('GET', `/api/agent/${name}/consistency`, { ...options });
  }

  /**
   * Get relationship network
   * Returns rivals and allies for the agent
   */
  async getAgentBynameNetwork(
    name: string,
    options?: RequestOptions,
  ): Promise<RelationshipNetwork> {
    return this.request<RelationshipNetwork>('GET', `/api/agent/${name}/network`, { ...options });
  }

  /**
   * Compare multiple agents
   */
  async getAgentCompare(
    query?: { agents: string[] },
    options?: RequestOptions,
  ): Promise<AgentComparison> {
    const queryParams = query ? { agents: query.agents.join(',') } : undefined;
    return this.request<AgentComparison>('GET', `/api/agent/compare`, {
      ...options,
      query: queryParams,
    });
  }

  /**
   * Get recent position flips
   */
  async getFlipsRecent(
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ flips?: PositionFlip[] }> {
    return this.request<{ flips?: PositionFlip[] }>('GET', `/api/flips/recent`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Health check
   */
  async getHealth(options?: RequestOptions): Promise<{ status?: 'healthy' | 'degraded' }> {
    return this.request<{ status?: 'healthy' | 'degraded' }>('GET', `/api/health`, { ...options });
  }

  /**
   * Detailed health check
   */
  async getHealthDetailed(options?: RequestOptions): Promise<DetailedHealth> {
    return this.request<DetailedHealth>('GET', `/api/health/detailed`, { ...options });
  }

  /**
   * Get nomic loop state
   */
  async getNomicState(options?: RequestOptions): Promise<NomicState> {
    return this.request<NomicState>('GET', `/api/nomic/state`, { ...options });
  }

  /**
   * Get nomic health
   * Includes stall detection (30 minute threshold)
   */
  async getNomicHealth(options?: RequestOptions): Promise<NomicHealth> {
    return this.request<NomicHealth>('GET', `/api/nomic/health`, { ...options });
  }

  /**
   * Get available modes
   */
  async getModes(options?: RequestOptions): Promise<{ modes?: Mode[] }> {
    return this.request<{ modes?: Mode[] }>('GET', `/api/modes`, { ...options });
  }

  /**
   * Find similar debates
   */
  async getConsensusSimilar(
    query?: { topic: string; limit?: number },
    options?: RequestOptions,
  ): Promise<{ similar?: SimilarDebate[] }> {
    return this.request<{ similar?: SimilarDebate[] }>('GET', `/api/consensus/similar`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get settled topics
   */
  async getConsensusSettled(
    query?: { min_confidence?: number; limit?: number },
    options?: RequestOptions,
  ): Promise<{ settled?: SettledTopic[] }> {
    return this.request<{ settled?: SettledTopic[] }>('GET', `/api/consensus/settled`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get consensus statistics
   */
  async getConsensusStats(options?: RequestOptions): Promise<ConsensusStats> {
    return this.request<ConsensusStats>('GET', `/api/consensus/stats`, { ...options });
  }

  /**
   * Get dissenting views
   */
  async getConsensusDissents(
    query?: { topic?: string; domain?: string; limit?: number },
    options?: RequestOptions,
  ): Promise<{ dissents?: Dissent[] }> {
    return this.request<{ dissents?: Dissent[] }>('GET', `/api/consensus/dissents`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Retrieve memories
   */
  async getMemoryContinuumRetrieve(
    query?: {
      query: string;
      tiers?: 'fast' | 'medium' | 'slow' | 'glacial'[];
      limit?: number;
      min_importance?: number;
    },
    options?: RequestOptions,
  ): Promise<{ memories?: Memory[] }> {
    return this.request<{ memories?: Memory[] }>('GET', `/api/memory/continuum/retrieve`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Trigger consolidation
   */
  async postMemoryContinuumConsolidate(
    options?: RequestOptions,
  ): Promise<{ promoted?: number; demoted?: number }> {
    return this.request<{ promoted?: number; demoted?: number }>(
      'POST',
      `/api/memory/continuum/consolidate`,
      { ...options },
    );
  }

  /**
   * Get tier statistics
   */
  async getMemoryTier_stats(options?: RequestOptions): Promise<TierStats> {
    return this.request<TierStats>('GET', `/api/memory/tier-stats`, { ...options });
  }

  /**
   * List tournaments
   */
  async getTournaments(options?: RequestOptions): Promise<{ tournaments?: Tournament[] }> {
    return this.request<{ tournaments?: Tournament[] }>('GET', `/api/tournaments`, { ...options });
  }

  /**
   * Get tournament standings
   */
  async getTournamentsByidStandings(
    id: string,
    options?: RequestOptions,
  ): Promise<TournamentStandings> {
    return this.request<TournamentStandings>('GET', `/api/tournaments/${id}/standings`, {
      ...options,
    });
  }

  /**
   * List replays
   */
  async getReplays(options?: RequestOptions): Promise<{ replays?: ReplaySummary[] }> {
    return this.request<{ replays?: ReplaySummary[] }>('GET', `/api/replays`, { ...options });
  }

  /**
   * Get replay
   */
  async getReplaysByreplay_id(
    replay_id: string,
    query?: { offset?: number; limit?: number },
    options?: RequestOptions,
  ): Promise<Replay> {
    return this.request<Replay>('GET', `/api/replays/${replay_id}`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * List documents
   */
  async getDocuments(options?: RequestOptions): Promise<{ documents?: DocumentSummary[] }> {
    return this.request<{ documents?: DocumentSummary[] }>('GET', `/api/documents`, { ...options });
  }

  /**
   * Get supported formats
   */
  async getDocumentsFormats(options?: RequestOptions): Promise<SupportedFormats> {
    return this.request<SupportedFormats>('GET', `/api/documents/formats`, { ...options });
  }

  /**
   * Get document
   */
  async getDocumentsBydoc_id(doc_id: string, options?: RequestOptions): Promise<Document> {
    return this.request<Document>('GET', `/api/documents/${doc_id}`, { ...options });
  }

  /**
   * Get verification backend status
   */
  async getVerificationStatus(options?: RequestOptions): Promise<VerificationStatus> {
    return this.request<VerificationStatus>('GET', `/api/verification/status`, { ...options });
  }

  /**
   * Verify claim formally
   */
  async postVerificationFormal_verify(
    body: {
      /** Claim to verify */
      claim: string;
      claim_type?: string;
      context?: string;
      timeout?: number;
    },
    options?: RequestOptions,
  ): Promise<VerificationResult> {
    return this.request<VerificationResult>('POST', `/api/verification/formal-verify`, {
      ...options,
      body,
    });
  }

  /**
   * Get disagreement statistics
   */
  async getAnalyticsDisagreements(options?: RequestOptions): Promise<DisagreementStats> {
    return this.request<DisagreementStats>('GET', `/api/analytics/disagreements`, { ...options });
  }

  /**
   * Get ranking statistics
   */
  async getRankingStats(options?: RequestOptions): Promise<RankingStats> {
    return this.request<RankingStats>('GET', `/api/ranking/stats`, { ...options });
  }

  /**
   * Get relationship overview
   */
  async getRelationshipsSummary(options?: RequestOptions): Promise<RelationshipSummary> {
    return this.request<RelationshipSummary>('GET', `/api/relationships/summary`, { ...options });
  }

  /**
   * Get relationship graph
   */
  async getRelationshipsGraph(
    query?: { min_debates?: number; min_score?: number },
    options?: RequestOptions,
  ): Promise<RelationshipGraph> {
    return this.request<RelationshipGraph>('GET', `/api/relationships/graph`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get relationship between agents
   */
  async getRelationshipByagent_aByagent_b(
    agent_a: string,
    agent_b: string,
    options?: RequestOptions,
  ): Promise<Relationship> {
    return this.request<Relationship>('GET', `/api/relationship/${agent_a}/${agent_b}`, {
      ...options,
    });
  }

  /**
   * Get moments overview
   */
  async getMomentsSummary(options?: RequestOptions): Promise<MomentsSummary> {
    return this.request<MomentsSummary>('GET', `/api/moments/summary`, { ...options });
  }

  /**
   * Get moments timeline
   */
  async getMomentsTimeline(
    query?: { limit?: number; offset?: number },
    options?: RequestOptions,
  ): Promise<{ moments?: Moment[] }> {
    return this.request<{ moments?: Moment[] }>('GET', `/api/moments/timeline`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get trending moments
   */
  async getMomentsTrending(
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ moments?: Moment[] }> {
    return this.request<{ moments?: Moment[] }>('GET', `/api/moments/trending`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get dashboard debate metrics
   */
  async getDashboardDebates(
    query?: { domain?: string; limit?: number; hours?: number },
    options?: RequestOptions,
  ): Promise<DashboardMetrics> {
    return this.request<DashboardMetrics>('GET', `/api/dashboard/debates`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get trending topics
   */
  async getPulseTrending(
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ topics?: TrendingTopic[] }> {
    return this.request<{ topics?: TrendingTopic[] }>('GET', `/api/pulse/trending`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Start a debate on a trending topic
   * @requires Authentication
   */
  async postPulseDebate_topic(
    body: {
      /** Topic to debate */
      topic: string;
      rounds?: number;
      consensus_threshold?: number;
    },
    options?: RequestOptions,
  ): Promise<{ debate_id?: string; topic?: string; status?: string }> {
    return this.request<{ debate_id?: string; topic?: string; status?: string }>(
      'POST',
      `/api/pulse/debate-topic`,
      { ...options, body },
    );
  }

  /**
   * Get pulse scheduler status
   */
  async getPulseSchedulerStatus(options?: RequestOptions): Promise<SchedulerStatus> {
    return this.request<SchedulerStatus>('GET', `/api/pulse/scheduler/status`, { ...options });
  }

  /**
   * Start the pulse scheduler
   * @requires Authentication
   */
  async postPulseSchedulerStart(
    options?: RequestOptions,
  ): Promise<{ status?: string; run_id?: string }> {
    return this.request<{ status?: string; run_id?: string }>(
      'POST',
      `/api/pulse/scheduler/start`,
      { ...options },
    );
  }

  /**
   * Stop the pulse scheduler
   * @requires Authentication
   */
  async postPulseSchedulerStop(options?: RequestOptions): Promise<{ status?: string }> {
    return this.request<{ status?: string }>('POST', `/api/pulse/scheduler/stop`, { ...options });
  }

  /**
   * Pause the pulse scheduler
   * @requires Authentication
   */
  async postPulseSchedulerPause(options?: RequestOptions): Promise<{ status?: string }> {
    return this.request<{ status?: string }>('POST', `/api/pulse/scheduler/pause`, { ...options });
  }

  /**
   * Resume the pulse scheduler
   * @requires Authentication
   */
  async postPulseSchedulerResume(options?: RequestOptions): Promise<{ status?: string }> {
    return this.request<{ status?: string }>('POST', `/api/pulse/scheduler/resume`, { ...options });
  }

  /**
   * Update scheduler configuration
   * @requires Authentication
   */
  async patchPulseSchedulerConfig(
    body: {
      poll_interval_seconds?: number;
      max_debates_per_hour?: number;
      min_volume_threshold?: number;
      min_controversy_score?: number;
      dedup_window_hours?: number;
    },
    options?: RequestOptions,
  ): Promise<{ status?: string; config?: Record<string, unknown> }> {
    return this.request<{ status?: string; config?: Record<string, unknown> }>(
      'PATCH',
      `/api/pulse/scheduler/config`,
      { ...options, body },
    );
  }

  /**
   * Get scheduled debate history
   */
  async getPulseSchedulerHistory(
    query?: { limit?: number; offset?: number; platform?: string; category?: string },
    options?: RequestOptions,
  ): Promise<{ history?: ScheduledDebateRecord[]; total?: number }> {
    return this.request<{ history?: ScheduledDebateRecord[]; total?: number }>(
      'GET',
      `/api/pulse/scheduler/history`,
      { ...options, query: query as Record<string, string | number | undefined> },
    );
  }

  /**
   * Get Slack integration status
   */
  async getIntegrationsSlackStatus(
    options?: RequestOptions,
  ): Promise<{
    enabled?: boolean;
    signing_secret_configured?: boolean;
    bot_token_configured?: boolean;
    webhook_configured?: boolean;
  }> {
    return this.request<{
      enabled?: boolean;
      signing_secret_configured?: boolean;
      bot_token_configured?: boolean;
      webhook_configured?: boolean;
    }>('GET', `/api/integrations/slack/status`, { ...options });
  }

  /**
   * Handle Slack slash commands
   * Endpoint for Slack to POST slash command payloads
   */
  async postIntegrationsSlackCommands(
    body: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<{
    response_type?: 'ephemeral' | 'in_channel';
    text?: string;
    blocks?: Record<string, unknown>[];
  }> {
    return this.request<{
      response_type?: 'ephemeral' | 'in_channel';
      text?: string;
      blocks?: Record<string, unknown>[];
    }>('POST', `/api/integrations/slack/commands`, { ...options, body });
  }

  /**
   * Handle Slack interactive components
   * Endpoint for Slack interactive component callbacks
   */
  async postIntegrationsSlackInteractive(
    body: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('POST', `/api/integrations/slack/interactive`, {
      ...options,
      body,
    });
  }

  /**
   * Handle Slack Events API
   * Endpoint for Slack event subscriptions
   */
  async postIntegrationsSlackEvents(
    body: { type?: string; challenge?: string; event?: Record<string, unknown> },
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('POST', `/api/integrations/slack/events`, {
      ...options,
      body,
    });
  }

  /**
   * Run capability probes on an agent
   * Execute capability probes to detect vulnerabilities and weaknesses.
Probes test for contradiction handling, hallucination, sycophancy, and more.

   * @requires Authentication
   */
  async postProbesCapability(
    body: {
      /** Name of the agent to probe */
      agent_name: string;
      /** Types of probes to run (default all) */
      probe_types?:
        | 'contradiction'
        | 'hallucination'
        | 'sycophancy'
        | 'persistence'
        | 'confidence_calibration'
        | 'reasoning_depth'
        | 'edge_case'[];
      /** Number of probes per type */
      probes_per_type?: number;
      /** Agent model type */
      model_type?: string;
    },
    options?: RequestOptions,
  ): Promise<ProbeReport> {
    return this.request<ProbeReport>('POST', `/api/probes/capability`, { ...options, body });
  }

  /**
   * Get emergent traits from agent performance
   * Detect emergent behavioral traits from agent debate patterns
   */
  async getLaboratoryEmergent_traits(
    query?: { min_confidence?: number; limit?: number },
    options?: RequestOptions,
  ): Promise<{ emergent_traits?: EmergentTrait[]; count?: number; min_confidence?: number }> {
    return this.request<{
      emergent_traits?: EmergentTrait[];
      count?: number;
      min_confidence?: number;
    }>('GET', `/api/laboratory/emergent-traits`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Suggest beneficial trait transfers
   * Analyze agents and suggest which traits could be transferred between them
   * @requires Authentication
   */
  async postLaboratoryCross_pollinationsSuggest(
    body: { source_agents?: string[]; target_agents?: string[]; min_benefit_score?: number },
    options?: RequestOptions,
  ): Promise<{ suggestions?: CrossPollinationSuggestion[] }> {
    return this.request<{ suggestions?: CrossPollinationSuggestion[] }>(
      'POST',
      `/api/laboratory/cross-pollinations/suggest`,
      { ...options, body },
    );
  }

  /**
   * Get recent insights
   * Retrieve recently extracted insights from debates
   */
  async getInsightsRecent(
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ insights?: Insight[] }> {
    return this.request<{ insights?: Insight[] }>('GET', `/api/insights/recent`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Extract detailed insights from content
   * Analyze content and extract structured insights
   * @requires Authentication
   */
  async postInsightsExtract_detailed(
    body: {
      /** Content to analyze */
      content: string;
      /** Optional context for analysis */
      context?: string;
    },
    options?: RequestOptions,
  ): Promise<{ insights?: Insight[]; metadata?: Record<string, unknown> }> {
    return this.request<{ insights?: Insight[]; metadata?: Record<string, unknown> }>(
      'POST',
      `/api/insights/extract-detailed`,
      { ...options, body },
    );
  }

  /**
   * Get best-performing team combinations
   * Retrieve historical best-performing agent team combinations
   */
  async getRoutingBest_teams(
    query?: { min_debates?: number; limit?: number },
    options?: RequestOptions,
  ): Promise<{ min_debates?: number; combinations?: TeamCombination[]; count?: number }> {
    return this.request<{ min_debates?: number; combinations?: TeamCombination[]; count?: number }>(
      'GET',
      `/api/routing/best-teams`,
      { ...options, query: query as Record<string, string | number | undefined> },
    );
  }

  /**
   * Get agent recommendations for a task
   * Get ranked agent recommendations based on task requirements
   * @requires Authentication
   */
  async postRoutingRecommendations(
    body: {
      /** Primary domain for the task */
      primary_domain?: string;
      secondary_domains?: string[];
      required_traits?: string[];
      task_id?: string;
      limit?: number;
    },
    options?: RequestOptions,
  ): Promise<{ recommendations?: AgentRecommendation[] }> {
    return this.request<{ recommendations?: AgentRecommendation[] }>(
      'POST',
      `/api/routing/recommendations`,
      { ...options, body },
    );
  }

  /**
   * Get top evolution patterns
   * Returns the most successful patterns extracted from winning debate strategies
   */
  async getEvolutionPatterns(
    query?: { type?: 'argument' | 'structure' | 'citation' | 'all'; limit?: number },
    options?: RequestOptions,
  ): Promise<{ patterns?: EvolutionPattern[] }> {
    return this.request<{ patterns?: EvolutionPattern[] }>('GET', `/api/evolution/patterns`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Get evolution summary
   * Returns aggregate statistics about prompt evolution
   */
  async getEvolutionSummary(
    options?: RequestOptions,
  ): Promise<{
    total_patterns?: number;
    agents_evolved?: number;
    success_rate?: number;
    last_evolution?: string;
  }> {
    return this.request<{
      total_patterns?: number;
      agents_evolved?: number;
      success_rate?: number;
      last_evolution?: string;
    }>('GET', `/api/evolution/summary`, { ...options });
  }

  /**
   * Get agent evolution history
   * Returns prompt evolution history for a specific agent
   */
  async getEvolutionByagentHistory(
    agent: string,
    query?: { limit?: number },
    options?: RequestOptions,
  ): Promise<{ agent?: string; history?: EvolutionEvent[] }> {
    return this.request<{ agent?: string; history?: EvolutionEvent[] }>(
      'GET',
      `/api/evolution/${agent}/history`,
      { ...options, query: query as Record<string, string | number | undefined> },
    );
  }

  /**
   * Get agent prompt
   * Returns current or specific version of agent's evolved prompt
   */
  async getEvolutionByagentPrompt(
    agent: string,
    query?: { version?: number },
    options?: RequestOptions,
  ): Promise<{ agent?: string; version?: number; prompt?: string; patterns_applied?: string[] }> {
    return this.request<{
      agent?: string;
      version?: number;
      prompt?: string;
      patterns_applied?: string[];
    }>('GET', `/api/evolution/${agent}/prompt`, {
      ...options,
      query: query as Record<string, string | number | undefined>,
    });
  }

  /**
   * Generate podcast audio
   * Generates podcast-style audio from a debate trace
   * @requires Authentication
   */
  async postDebatesByidBroadcast(
    id: string,
    body?: {
      /** Agent to voice mapping */
      voice_mapping?: Record<string, string>;
      include_intro?: boolean;
      include_outro?: boolean;
    },
    options?: RequestOptions,
  ): Promise<{ job_id?: string; status?: 'queued' | 'processing' | 'completed' | 'failed' }> {
    return this.request<{
      job_id?: string;
      status?: 'queued' | 'processing' | 'completed' | 'failed';
    }>('POST', `/api/debates/${id}/broadcast`, { ...options, body });
  }

  /**
   * Run full broadcast pipeline
   * Runs complete broadcast pipeline including TTS, mixing, and publishing
   * @requires Authentication
   */
  async postDebatesByidBroadcastFull(
    id: string,
    body?: {
      platforms?: 'rss' | 'youtube' | 'twitter'[];
      tts_backend?: 'elevenlabs' | 'google' | 'openai';
    },
    options?: RequestOptions,
  ): Promise<{
    job_id?: string;
    status?: string;
    /** Estimated completion time in seconds */
    estimated_duration?: number;
  }> {
    return this.request<{
      job_id?: string;
      status?: string;
      /** Estimated completion time in seconds */
      estimated_duration?: number;
    }>('POST', `/api/debates/${id}/broadcast/full`, { ...options, body });
  }

  /**
   * Get podcast RSS feed
   * Returns RSS feed for the Aragora podcast
   */
  async getPodcastFeedXml(options?: RequestOptions): Promise<unknown> {
    return this.request<unknown>('GET', `/api/podcast/feed.xml`, { ...options });
  }
}

// Default instance factory
export function createApiClient(config: Partial<ApiClientConfig> = {}): AragoraApiClient {
  return new AragoraApiClient({ baseUrl: config.baseUrl || API_BASE_URL, ...config });
}
