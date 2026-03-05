/**
 * Debates Namespace API
 *
 * Provides a namespaced interface for debate-related operations.
 * This wraps the flat client methods for a more intuitive API.
 */

import type {
  Debate,
  DebateCreateRequest,
  DebateCreateResponse,
  DebateConvergence,
  DebateCitations,
  DebateEvidence,
  DebateExport,
  DebateUpdateRequest,
  GraphStats,
  Message,
  PaginationParams,
  WebSocketEvent,
} from '../types';
import type { StreamOptions } from '../websocket';
import { AsyncPaginator } from '../pagination';

/**
 * Debate impasse analysis result
 */
export interface DebateImpasse {
  is_impasse: boolean;
  confidence: number;
  reason: string | null;
  stuck_since_round: number | null;
  suggested_intervention: string | null;
}

/**
 * Rhetorical pattern observation
 */
export interface RhetoricalObservation {
  agent: string;
  pattern: string;
  description: string;
  severity: number;
  round: number;
  timestamp: string;
}

/**
 * Rhetorical analysis response
 */
export interface RhetoricalAnalysis {
  debate_id: string;
  observations: RhetoricalObservation[];
  summary: {
    total_observations: number;
    patterns_detected: string[];
    agents_flagged: string[];
  };
}

/**
 * Trickster hollow consensus status
 */
export interface TricksterStatus {
  debate_id: string;
  hollow_consensus_detected: boolean;
  confidence: number;
  indicators: Array<{
    type: string;
    description: string;
    severity: number;
  }>;
  recommendation: string | null;
}

/**
 * Overall debate health status
 */
export interface DebateHealthStatus {
  active_count: number;
  stuck_count: number;
  healthy_count: number;
  stuck_debates: Array<{
    debate_id: string;
    task: string;
    stuck_since: string;
    stuck_since_round: number;
  }>;
  last_updated: string;
}

/**
 * Health detail for a specific debate
 */
export interface DebateHealthDetail {
  debate_id: string;
  status: 'healthy' | 'stuck' | 'stalled' | 'completed';
  stuck_since_round: number | null;
  current_round: number;
  last_activity: string;
  agents_active: string[];
  recommendations: string[];
}

/**
 * Debate filter options
 */
export interface DebateFilters {
  status?: string;
  domain?: string;
  agents?: string[];
  minRounds?: number;
  maxRounds?: number;
  consensusReached?: boolean;
  since?: string;
  until?: string;
  orderBy?: string;
  orderDir?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

/**
 * Debate statistics
 */
export interface DebateStatistics {
  total_debates: number;
  completed_debates: number;
  consensus_rate: number;
  avg_rounds: number;
  avg_duration_seconds: number;
  by_status: Record<string, number>;
  by_domain: Record<string, number>;
  period: string;
}

/**
 * Agent performance statistics
 */
export interface DebateAgentStatistics {
  agents: Array<{
    name: string;
    debates_participated: number;
    win_rate: number;
    avg_quality_score: number;
    consensus_contribution: number;
  }>;
  period: string;
}

/**
 * Consensus analytics
 */
export interface ConsensusAnalytics {
  reached_count: number;
  total_debates: number;
  avg_confidence: number;
  avg_rounds_to_consensus: number;
  by_domain: Record<string, { reached: number; total: number }>;
  period: string;
}

/**
 * Topic trends in debates
 */
export interface TopicTrends {
  topics: Array<{
    name: string;
    count: number;
    velocity: number;
    trend: 'rising' | 'stable' | 'declining';
  }>;
  period: string;
}

/**
 * Batch export result
 */
export interface BatchExportResult {
  batch_id: string;
  count: number;
  format: string;
  download_url: string;
  expires_at: string;
}

/**
 * Batch operation results
 */
export interface BatchResults {
  batch_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  debates: Array<{
    debate_id: string;
    status: 'success' | 'failed' | 'pending';
    error?: string;
  }>;
}

/**
 * Debate comparison result
 */
export interface DebateComparison {
  debate_ids: string[];
  similarity_score: number;
  common_themes: string[];
  divergent_points: Array<{
    topic: string;
    positions: Record<string, string>;
  }>;
  consensus_alignment: number;
}

/**
 * Argument quality analysis
 */
export interface ArgumentQualityAnalysis {
  debate_id: string;
  overall_score: number;
  by_agent: Array<{
    name: string;
    quality_score: number;
    evidence_usage: number;
    logical_consistency: number;
    engagement_quality: number;
  }>;
  recommendations: string[];
}

/**
 * Debate note
 */
export interface DebateNote {
  note_id: string;
  debate_id: string;
  content: string;
  author: string;
  created_at: string;
  updated_at: string;
}

/**
 * Meta-critique analysis
 */
export interface MetaCritique {
  debate_id: string;
  quality_score: number;
  critique: string;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  agent_performance: Array<{
    agent: string;
    contribution_score: number;
    critique: string;
  }>;
}

/**
 * Debate summary with key points
 */
export interface DebateSummary {
  debate_id: string;
  verdict: string;
  confidence: number;
  key_points: string[];
  dissenting_views: string[];
  evidence_quality: number;
  generated_at: string;
}

/**
 * Verification report for debate conclusions
 */
export interface VerificationReport {
  debate_id: string;
  verified: boolean;
  confidence: number;
  claims_verified: number;
  claims_total: number;
  verification_details: Array<{
    claim: string;
    status: 'verified' | 'unverified' | 'disputed';
    evidence: string[];
    confidence: number;
  }>;
  bonuses: Array<{
    type: string;
    amount: number;
    reason: string;
  }>;
  generated_at: string;
}

/**
 * Claim verification result
 */
export interface ClaimVerification {
  claim_id: string;
  verified: boolean;
  confidence: number;
  supporting_evidence: string[];
  counter_evidence: string[];
  status: 'verified' | 'unverified' | 'disputed' | 'pending';
}

/**
 * Follow-up debate suggestion
 */
export interface FollowupSuggestion {
  id: string;
  topic: string;
  question: string;
  crux_id?: string;
  rationale: string;
  priority: 'high' | 'medium' | 'low';
  estimated_value: number;
}

/**
 * Fork information
 */
export interface ForkInfo {
  fork_id: string;
  parent_debate_id: string;
  branch_point: number;
  created_at: string;
  status: string;
  divergence_reason?: string;
}

/**
 * Debate search options
 */
export interface DebateSearchOptions {
  query: string;
  limit?: number;
  offset?: number;
  status?: string;
  domain?: string;
  since?: string;
  until?: string;
}

/**
 * Batch job status
 */
export interface BatchJob {
  job_id: string;
  debate_id?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress?: number;
  error?: string;
  created_at: string;
}

/**
 * Batch submission response
 */
export interface BatchSubmission {
  batch_id: string;
  jobs: BatchJob[];
  total_jobs: number;
  submitted_at: string;
}

/**
 * Batch status response
 */
export interface BatchStatus {
  batch_id: string;
  status: 'pending' | 'running' | 'completed' | 'partially_completed' | 'failed';
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  jobs: BatchJob[];
}

/**
 * Queue status information
 */
export interface QueueStatus {
  pending_count: number;
  running_count: number;
  completed_today: number;
  average_wait_time_ms: number;
  estimated_completion_time?: string;
}

/**
 * Graph visualization data
 */
export interface DebateGraph {
  nodes: Array<{
    id: string;
    type: 'claim' | 'evidence' | 'argument' | 'counter';
    content: string;
    agent: string;
    round: number;
    confidence?: number;
  }>;
  edges: Array<{
    source: string;
    target: string;
    type: 'supports' | 'attacks' | 'responds_to';
    weight?: number;
  }>;
  metadata: {
    total_nodes: number;
    total_edges: number;
    depth: number;
    branching_factor: number;
  };
}

/**
 * Graph branch information
 */
export interface GraphBranch {
  branch_id: string;
  root_node: string;
  depth: number;
  node_count: number;
  conclusion?: string;
}

/**
 * Matrix debate comparison
 */
export interface MatrixComparison {
  debate_id: string;
  scenarios: Array<{
    scenario_id: string;
    name: string;
    parameters: Record<string, unknown>;
    outcome: string;
    confidence: number;
  }>;
  comparison_matrix: Array<Array<number>>;
  dominant_scenario?: string;
  sensitivity_analysis?: Record<string, number>;
}

/**
 * Interface for the internal client methods used by DebatesAPI.
 * This allows the namespace to work without circular imports.
 */
interface DebatesClientInterface {
  listDebates(params?: PaginationParams & { status?: string }): Promise<{ debates: Debate[] }>;
  getDebate(debateId: string): Promise<Debate>;
  getDebateBySlug(slug: string): Promise<Debate>;
  createDebate(request: DebateCreateRequest): Promise<DebateCreateResponse>;
  getDebateMessages(debateId: string): Promise<{ messages: Message[] }>;
  getDebateConvergence(debateId: string): Promise<DebateConvergence>;
  getDebateCitations(debateId: string): Promise<DebateCitations>;
  getDebateEvidence(debateId: string): Promise<DebateEvidence>;
  forkDebate(debateId: string, options?: { branch_point?: number }): Promise<{ debate_id: string }>;
  exportDebate(debateId: string, format: 'json' | 'markdown' | 'html' | 'pdf'): Promise<DebateExport>;
  updateDebate(debateId: string, updates: DebateUpdateRequest): Promise<Debate>;
  getDebateGraphStats(debateId: string): Promise<GraphStats>;
  createDebateAndStream(
    request: DebateCreateRequest,
    streamOptions?: Omit<StreamOptions, 'debateId'>
  ): Promise<{ debate: DebateCreateResponse; stream: AsyncGenerator<WebSocketEvent, void, unknown> }>;
  runDebate(
    request: DebateCreateRequest,
    options?: { pollIntervalMs?: number; timeoutMs?: number }
  ): Promise<Debate>;
  request<T>(method: string, path: string, options?: { params?: Record<string, unknown>; body?: unknown }): Promise<T>;
}

/**
 * Debates API namespace.
 *
 * Provides methods for managing debates:
 * - Creating and running debates
 * - Retrieving debate details and messages
 * - Exporting debates in various formats
 * - Analyzing debate convergence and evidence
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Create a debate
 * const response = await client.debates.create({
 *   task: 'Should we use microservices?',
 *   agents: ['claude', 'gpt-4'],
 * });
 *
 * // Get debate details
 * const debate = await client.debates.get(response.debate_id);
 *
 * // List all debates
 * const { debates } = await client.debates.list({ limit: 10 });
 *
 * // Export as markdown
 * const export = await client.debates.export(debateId, 'markdown');
 * ```
 */
export class DebatesAPI {
  constructor(private client: DebatesClientInterface) {}

  // ===========================================================================
  // Core CRUD Operations
  // ===========================================================================

  /**
   * List all debates with optional filtering and pagination.
   */
  async list(params?: PaginationParams & { status?: string }): Promise<{ debates: Debate[] }> {
    return this.client.listDebates(params);
  }

  /**
   * Get a debate by ID.
   */
  async get(debateId: string): Promise<Debate> {
    return this.client.getDebate(debateId);
  }

  /**
   * Get a debate by its URL slug.
   */
  async getBySlug(slug: string): Promise<Debate> {
    return this.client.getDebateBySlug(slug);
  }

  /**
   * Create a new debate.
   */
  async create(request: DebateCreateRequest): Promise<DebateCreateResponse> {
    return this.client.createDebate(request);
  }

  /**
   * Update an existing debate.
   */
  async update(debateId: string, updates: DebateUpdateRequest): Promise<Debate> {
    return this.client.updateDebate(debateId, updates);
  }

  /**
   * Delete a debate.
   *
   * @param debateId - The debate ID to delete
   *
   * @example
   * ```typescript
   * const result = await client.debates.delete('debate-123');
   * if (result.success) {
   *   console.log('Debate deleted');
   * }
   * ```
   */
  async delete(debateId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/v1/debates/${debateId}`);
  }

  /**
   * Get all messages from a debate.
   */
  async getMessages(debateId: string): Promise<{ messages: Message[] }> {
    return this.client.getDebateMessages(debateId);
  }

  /**
   * Add a message to a debate.
   *
   * @param debateId - The debate ID
   * @param content - Message content
   * @param role - Message role (user, system, etc.)
   *
   * @example
   * ```typescript
   * const message = await client.debates.addMessage('debate-123', 'What about security?', 'user');
   * console.log(`Message added: ${message.id}`);
   * ```
   */
  async addMessage(
    debateId: string,
    content: string,
    role: string = 'user'
  ): Promise<Message> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/messages`, {
      body: { content, role },
    });
  }

  /**
   * Get convergence analysis for a debate.
   */
  async getConvergence(debateId: string): Promise<DebateConvergence> {
    return this.client.getDebateConvergence(debateId);
  }

  /**
   * Get citations from a debate.
   */
  async getCitations(debateId: string): Promise<DebateCitations> {
    return this.client.getDebateCitations(debateId);
  }

  /**
   * Get evidence gathered during a debate.
   */
  async getEvidence(debateId: string): Promise<DebateEvidence> {
    return this.client.getDebateEvidence(debateId);
  }

  /**
   * Add evidence to a debate.
   *
   * @param debateId - The debate ID
   * @param evidence - Evidence content
   * @param source - Optional source of the evidence
   * @param metadata - Optional additional metadata
   *
   * @example
   * ```typescript
   * const result = await client.debates.addEvidence('debate-123', 'Studies show...', 'research-paper');
   * console.log(`Evidence added: ${result.evidence_id}`);
   * ```
   */
  async addEvidence(
    debateId: string,
    evidence: string,
    source?: string,
    metadata?: Record<string, unknown>
  ): Promise<{ evidence_id: string; success: boolean }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/evidence`, {
      body: { evidence, source, metadata },
    });
  }

  /**
   * Get consensus information for a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const consensus = await client.debates.getConsensus('debate-123');
   * if (consensus.reached) {
   *   console.log(`Consensus: ${consensus.conclusion}`);
   * }
   * ```
   */
  async getConsensus(debateId: string): Promise<{
    reached: boolean;
    conclusion: string | null;
    confidence: number;
    dissent: string[];
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/consensus`);
  }

  /**
   * Fork a debate from a specific point.
   */
  async fork(debateId: string, options?: { branch_point?: number }): Promise<{ debate_id: string }> {
    return this.client.forkDebate(debateId, options);
  }

  /**
   * Clone a debate (create a copy with fresh state).
   *
   * @param debateId - The debate ID to clone
   * @param options - Optional clone options
   *
   * @example
   * ```typescript
   * const cloned = await client.debates.clone('debate-123', { preserveAgents: true });
   * console.log(`Cloned debate: ${cloned.debate_id}`);
   * ```
   */
  async clone(
    debateId: string,
    options?: { preserveAgents?: boolean; preserveContext?: boolean }
  ): Promise<{ debate_id: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/clone`, {
      body: options,
    });
  }

  /**
   * Archive a debate.
   *
   * @param debateId - The debate ID to archive
   *
   * @example
   * ```typescript
   * const result = await client.debates.archive('debate-123');
   * if (result.success) {
   *   console.log('Debate archived');
   * }
   * ```
   */
  async archive(debateId: string): Promise<{ success: boolean }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/archive`);
  }

  /**
   * Export a debate in a specific format.
   */
  async export(debateId: string, format: 'json' | 'markdown' | 'html' | 'pdf'): Promise<DebateExport> {
    return this.client.exportDebate(debateId, format);
  }

  /**
   * Get graph statistics for a debate.
   */
  async getGraphStats(debateId: string): Promise<GraphStats> {
    return this.client.getDebateGraphStats(debateId);
  }

  /**
   * Create a debate and return a stream of events.
   */
  async createAndStream(
    request: DebateCreateRequest,
    streamOptions?: Omit<StreamOptions, 'debateId'>
  ): Promise<{ debate: DebateCreateResponse; stream: AsyncGenerator<WebSocketEvent, void, unknown> }> {
    return this.client.createDebateAndStream(request, streamOptions);
  }

  /**
   * Create a debate and wait for it to complete.
   * Polls the debate status until it reaches a terminal state.
   */
  async run(
    request: DebateCreateRequest,
    options?: { pollIntervalMs?: number; timeoutMs?: number }
  ): Promise<Debate> {
    return this.client.runDebate(request, options);
  }

  /**
   * Alias for run() - creates a debate and waits for completion.
   */
  async waitForCompletion(debateId: string, options?: { pollIntervalMs?: number; timeoutMs?: number }): Promise<Debate> {
    const pollInterval = options?.pollIntervalMs ?? 1000;
    const timeout = options?.timeoutMs ?? 300000;
    const startTime = Date.now();

    while (Date.now() - startTime < timeout) {
      const debate = await this.client.getDebate(debateId);
      if (['completed', 'failed', 'cancelled'].includes(debate.status)) {
        return debate;
      }
      await new Promise(resolve => setTimeout(resolve, pollInterval));
    }

    throw new Error(`Debate ${debateId} did not complete within ${timeout}ms`);
  }

  // ===========================================================================
  // Analysis
  // ===========================================================================

  /**
   * Detect if a debate has reached an impasse.
   *
   * An impasse occurs when the debate is stuck and not making progress
   * toward consensus. This helps identify when intervention may be needed.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const impasse = await client.debates.getImpasse('debate-123');
   * if (impasse.is_impasse) {
   *   console.log(`Impasse detected: ${impasse.reason}`);
   *   console.log(`Suggested: ${impasse.suggested_intervention}`);
   * }
   * ```
   */
  async getImpasse(debateId: string): Promise<DebateImpasse> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/impasse`);
  }

  /**
   * Get rhetorical pattern observations for a debate.
   *
   * Analyzes the debate for rhetorical patterns that may indicate
   * manipulation, circular reasoning, or other issues.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const analysis = await client.debates.getRhetorical('debate-123');
   * console.log(`Found ${analysis.observations.length} rhetorical patterns`);
   * for (const obs of analysis.observations) {
   *   console.log(`${obs.agent}: ${obs.pattern} (severity: ${obs.severity})`);
   * }
   * ```
   */
  async getRhetorical(debateId: string): Promise<RhetoricalAnalysis> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/rhetorical`);
  }

  /**
   * Get trickster hollow consensus detection status.
   *
   * The Trickster detects "hollow consensus" - apparent agreement that
   * masks underlying disagreement or manipulation.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const status = await client.debates.getTrickster('debate-123');
   * if (status.hollow_consensus_detected) {
   *   console.log(`Warning: Hollow consensus detected (${status.confidence})`);
   *   for (const ind of status.indicators) {
   *     console.log(`- ${ind.type}: ${ind.description}`);
   *   }
   * }
   * ```
   */
  async getTrickster(debateId: string): Promise<TricksterStatus> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/trickster`);
  }

  /**
   * Get meta-level critique of the debate.
   *
   * Provides an overall analysis of debate quality, including
   * strengths, weaknesses, and recommendations.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const meta = await client.debates.getMetaCritique('debate-123');
   * console.log(`Overall quality: ${meta.quality_score}/100`);
   * console.log(`Strengths: ${meta.strengths.join(', ')}`);
   * console.log(`Weaknesses: ${meta.weaknesses.join(', ')}`);
   * ```
   */
  async getMetaCritique(debateId: string): Promise<MetaCritique> {
    return this.client.request('GET', `/api/v1/debate/${debateId}/meta-critique`);
  }

  // ===========================================================================
  // Summary & Verification
  // ===========================================================================

  /**
   * Get a human-readable summary of the debate.
   *
   * Provides a condensed verdict with key points, confidence level,
   * and any dissenting views that emerged.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const summary = await client.debates.getSummary('debate-123');
   * console.log(`Verdict: ${summary.verdict}`);
   * console.log(`Confidence: ${summary.confidence}%`);
   * console.log('Key points:', summary.key_points);
   * ```
   */
  async getSummary(debateId: string): Promise<DebateSummary> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/summary`);
  }

  /**
   * Get the verification report for debate conclusions.
   *
   * Shows which claims were verified, evidence quality, and any
   * bonuses awarded for verified conclusions.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const report = await client.debates.getVerificationReport('debate-123');
   * console.log(`Verified: ${report.claims_verified}/${report.claims_total}`);
   * for (const detail of report.verification_details) {
   *   console.log(`${detail.claim}: ${detail.status}`);
   * }
   * ```
   */
  async getVerificationReport(debateId: string): Promise<VerificationReport> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/verification-report`);
  }

  /**
   * Verify a specific claim from the debate.
   *
   * @param debateId - The debate ID
   * @param claimId - The claim to verify
   * @param evidence - Optional additional evidence to consider
   *
   * @example
   * ```typescript
   * const result = await client.debates.verifyClaim('debate-123', 'claim-456');
   * if (result.verified) {
   *   console.log(`Claim verified with ${result.confidence}% confidence`);
   * }
   * ```
   */
  async verifyClaim(
    debateId: string,
    claimId: string,
    evidence?: string
  ): Promise<ClaimVerification> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/verify`, {
      body: { claim_id: claimId, evidence },
    });
  }

  // ===========================================================================
  // Follow-up & Continuation
  // ===========================================================================

  /**
   * Get suggestions for follow-up debates.
   *
   * Based on unresolved cruxes, dissenting views, or areas
   * that warrant deeper exploration.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const suggestions = await client.debates.getFollowupSuggestions('debate-123');
   * for (const s of suggestions) {
   *   console.log(`${s.priority}: ${s.question}`);
   *   console.log(`  Rationale: ${s.rationale}`);
   * }
   * ```
   */
  async getFollowupSuggestions(debateId: string): Promise<FollowupSuggestion[]> {
    const response = await this.client.request<{ suggestions: FollowupSuggestion[] }>(
      'GET',
      `/api/v1/debates/${debateId}/followups`
    );
    return response.suggestions;
  }

  /**
   * Create a follow-up debate from an existing one.
   *
   * Can optionally target a specific crux for deeper exploration.
   *
   * @param debateId - The parent debate ID
   * @param options - Follow-up options
   *
   * @example
   * ```typescript
   * const followup = await client.debates.followUp('debate-123', {
   *   cruxId: 'crux-456',
   *   context: 'Focus on the security implications',
   * });
   * console.log(`New debate created: ${followup.debate_id}`);
   * ```
   */
  async followUp(
    debateId: string,
    options?: { cruxId?: string; context?: string }
  ): Promise<{ debate_id: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/followup`, {
      body: options,
    });
  }

  /**
   * List all forks created from a debate.
   *
   * @param debateId - The parent debate ID
   *
   * @example
   * ```typescript
   * const forks = await client.debates.listForks('debate-123');
   * console.log(`${forks.length} forks created`);
   * for (const fork of forks) {
   *   console.log(`Fork at round ${fork.branch_point}: ${fork.fork_id}`);
   * }
   * ```
   */
  async listForks(debateId: string): Promise<ForkInfo[]> {
    const response = await this.client.request<{ forks: ForkInfo[] }>(
      'GET',
      `/api/v1/debates/${debateId}/forks`
    );
    return response.forks;
  }

  // ===========================================================================
  // Debate Lifecycle
  // ===========================================================================

  /**
   * Start a debate.
   *
   * @param debateId - The debate ID to start
   *
   * @example
   * ```typescript
   * const result = await client.debates.start('debate-123');
   * console.log(`Debate started: ${result.status}`);
   * ```
   */
  async start(debateId: string): Promise<{ success: boolean; status: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/start`);
  }

  /**
   * Stop a running debate.
   *
   * @param debateId - The debate ID to stop
   *
   * @example
   * ```typescript
   * const result = await client.debates.stop('debate-123');
   * console.log(`Debate stopped: ${result.status}`);
   * ```
   */
  async stop(debateId: string): Promise<{ success: boolean; status: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/stop`);
  }

  /**
   * Pause a running debate.
   *
   * @param debateId - The debate ID to pause
   *
   * @example
   * ```typescript
   * const result = await client.debates.pause('debate-123');
   * console.log(`Debate paused: ${result.status}`);
   * ```
   */
  async pause(debateId: string): Promise<{ success: boolean; status: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/pause`);
  }

  /**
   * Resume a paused debate.
   *
   * @param debateId - The debate ID to resume
   *
   * @example
   * ```typescript
   * const result = await client.debates.resume('debate-123');
   * console.log(`Debate resumed: ${result.status}`);
   * ```
   */
  async resume(debateId: string): Promise<{ success: boolean; status: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/resume`);
  }

  /**
   * Cancel a running debate.
   *
   * @param debateId - The debate ID to cancel
   *
   * @example
   * ```typescript
   * const result = await client.debates.cancel('debate-123');
   * if (result.success) {
   *   console.log(`Debate cancelled: ${result.status}`);
   * }
   * ```
   */
  async cancel(debateId: string): Promise<{ success: boolean; status: string }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/cancel`);
  }

  // ===========================================================================
  // Rounds, Agents, and Votes
  // ===========================================================================

  /**
   * Get rounds from a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const rounds = await client.debates.getRounds('debate-123');
   * console.log(`${rounds.length} rounds completed`);
   * for (const round of rounds) {
   *   console.log(`Round ${round.number}: ${round.proposals.length} proposals`);
   * }
   * ```
   */
  async getRounds(debateId: string): Promise<Array<{
    number: number;
    proposals: Array<{ agent: string; content: string }>;
    critiques: Array<{ agent: string; target: string; content: string }>;
    status: string;
    started_at: string;
    ended_at?: string;
  }>> {
    const response = await this.client.request<{ rounds: Array<{
      number: number;
      proposals: Array<{ agent: string; content: string }>;
      critiques: Array<{ agent: string; target: string; content: string }>;
      status: string;
      started_at: string;
      ended_at?: string;
    }> }>('GET', `/api/v1/debates/${debateId}/rounds`);
    return response.rounds;
  }

  /**
   * Get agents participating in a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const agents = await client.debates.getAgents('debate-123');
   * for (const agent of agents) {
   *   console.log(`${agent.name}: ${agent.role} (ELO: ${agent.elo})`);
   * }
   * ```
   */
  async getAgents(debateId: string): Promise<Array<{
    name: string;
    role: string;
    model: string;
    elo?: number;
    contributions: number;
  }>> {
    const response = await this.client.request<{ agents: Array<{
      name: string;
      role: string;
      model: string;
      elo?: number;
      contributions: number;
    }> }>('GET', `/api/v1/debates/${debateId}/agents`);
    return response.agents;
  }

  /**
   * Get votes from a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const votes = await client.debates.getVotes('debate-123');
   * console.log(`${votes.length} votes cast`);
   * for (const vote of votes) {
   *   console.log(`${vote.agent} voted for: ${vote.position}`);
   * }
   * ```
   */
  async getVotes(debateId: string): Promise<Array<{
    agent: string;
    position: string;
    confidence: number;
    round: number;
    reasoning?: string;
  }>> {
    const response = await this.client.request<{ votes: Array<{
      agent: string;
      position: string;
      confidence: number;
      round: number;
      reasoning?: string;
    }> }>('GET', `/api/v1/debates/${debateId}/votes`);
    return response.votes;
  }

  /**
   * Add user input to a debate.
   *
   * @param debateId - The debate ID
   * @param input - User input content
   * @param inputType - Type of input (suggestion, vote, question, etc.)
   *
   * @example
   * ```typescript
   * const result = await client.debates.addUserInput('debate-123', 'Consider the scalability aspect', 'suggestion');
   * console.log(`Input added: ${result.input_id}`);
   * ```
   */
  async addUserInput(
    debateId: string,
    input: string,
    inputType: 'suggestion' | 'vote' | 'question' | 'context' = 'suggestion'
  ): Promise<{ input_id: string; success: boolean }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/user-input`, {
      body: { input, type: inputType },
    });
  }

  /**
   * Get the timeline of events in a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const timeline = await client.debates.getTimeline('debate-123');
   * for (const event of timeline) {
   *   console.log(`${event.timestamp}: ${event.type} - ${event.description}`);
   * }
   * ```
   */
  async getTimeline(debateId: string): Promise<Array<{
    timestamp: string;
    type: string;
    agent?: string;
    description: string;
    round?: number;
    metadata?: Record<string, unknown>;
  }>> {
    const response = await this.client.request<{ timeline: Array<{
      timestamp: string;
      type: string;
      agent?: string;
      description: string;
      round?: number;
      metadata?: Record<string, unknown>;
    }> }>('GET', `/api/v1/debates/${debateId}/timeline`);
    return response.timeline;
  }

  // ===========================================================================
  // Search & Discovery
  // ===========================================================================

  /**
   * Search across all debates.
   *
   * @param options - Search options including query, filters, and pagination
   *
   * @example
   * ```typescript
   * const results = await client.debates.search({
   *   query: 'microservices architecture',
   *   limit: 10,
   *   status: 'completed',
   * });
   * console.log(`Found ${results.debates.length} matching debates`);
   * ```
   */
  async search(options: DebateSearchOptions): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/search', {
      params: options as unknown as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Batch Operations
  // ===========================================================================

  /**
   * Submit multiple debates for batch processing.
   *
   * @param requests - Array of debate creation requests
   *
   * @example
   * ```typescript
   * const batch = await client.debates.submitBatch([
   *   { task: 'Should we use Redis?' },
   *   { task: 'Should we use PostgreSQL?' },
   * ]);
   * console.log(`Batch ${batch.batch_id} submitted with ${batch.total_jobs} jobs`);
   * ```
   */
  async submitBatch(requests: DebateCreateRequest[]): Promise<BatchSubmission> {
    return this.client.request('POST', '/api/v1/debates/batch', {
      body: { requests },
    });
  }

  /**
   * Get the status of a batch job.
   *
   * @param batchId - The batch ID
   *
   * @example
   * ```typescript
   * const status = await client.debates.getBatchStatus('batch-123');
   * console.log(`Progress: ${status.completed_jobs}/${status.total_jobs}`);
   * ```
   */
  async getBatchStatus(batchId: string): Promise<BatchStatus> {
    return this.client.request('GET', `/api/v1/debates/batch/${batchId}/status`);
  }

  /**
   * List all batch jobs.
   *
   * @param options - Filter options
   *
   * @example
   * ```typescript
   * const batches = await client.debates.listBatches({ limit: 10 });
   * for (const batch of batches) {
   *   console.log(`${batch.batch_id}: ${batch.status}`);
   * }
   * ```
   */
  async listBatches(options?: {
    limit?: number;
    offset?: number;
    status?: string;
  }): Promise<BatchStatus[]> {
    const response = await this.client.request<{ batches: BatchStatus[] }>('POST', '/api/v1/debates/batch',
      { params: options as Record<string, unknown> }
    );
    return response.batches;
  }

  /**
   * Get the current queue status.
   *
   * @example
   * ```typescript
   * const queue = await client.debates.getQueueStatus();
   * console.log(`${queue.pending_count} pending, ${queue.running_count} running`);
   * console.log(`Avg wait: ${queue.average_wait_time_ms}ms`);
   * ```
   */
  async getQueueStatus(): Promise<QueueStatus> {
    return this.client.request('GET', '/api/v1/debates/queue/status');
  }

  // ===========================================================================
  // Graph & Visualization
  // ===========================================================================

  /**
   * Get the argument graph for a debate.
   *
   * Returns nodes (claims, evidence, arguments) and edges (relationships)
   * for visualization.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const graph = await client.debates.getGraph('debate-123');
   * console.log(`${graph.nodes.length} nodes, ${graph.edges.length} edges`);
   * console.log(`Max depth: ${graph.metadata.depth}`);
   * ```
   */
  async getGraph(debateId: string): Promise<DebateGraph> {
    return this.client.request('GET', `/api/v1/debates/graph/${debateId}`);
  }

  /**
   * Get branches in the argument graph.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const branches = await client.debates.getGraphBranches('debate-123');
   * for (const branch of branches) {
   *   console.log(`Branch ${branch.branch_id}: ${branch.node_count} nodes`);
   * }
   * ```
   */
  async getGraphBranches(debateId: string): Promise<GraphBranch[]> {
    const response = await this.client.request<{ branches: GraphBranch[] }>(
      'GET',
      `/api/v1/debates/graph/${debateId}/branches`
    );
    return response.branches;
  }

  /**
   * Get matrix comparison for a multi-scenario debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const matrix = await client.debates.getMatrixComparison('debate-123');
   * console.log(`${matrix.scenarios.length} scenarios compared`);
   * if (matrix.dominant_scenario) {
   *   console.log(`Dominant: ${matrix.dominant_scenario}`);
   * }
   * ```
   */
  async getMatrixComparison(debateId: string): Promise<MatrixComparison> {
    return this.client.request('GET', `/api/v1/debates/matrix/${debateId}`);
  }

  // ===========================================================================
  // Explainability
  // ===========================================================================

  /**
   * Get explainability data for a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const explainability = await client.debates.getExplainability('debate-123');
   * console.log(`Decision explanation: ${explainability.narrative}`);
   * ```
   */
  async getExplainability(debateId: string): Promise<{
    debate_id: string;
    narrative: string;
    factors: Array<{ name: string; weight: number; description: string }>;
    confidence: number;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/explainability`);
  }

  /**
   * Get factor decomposition for a debate decision.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const factors = await client.debates.getExplainabilityFactors('debate-123');
   * for (const factor of factors.factors) {
   *   console.log(`${factor.name}: ${factor.weight} - ${factor.description}`);
   * }
   * ```
   */
  async getExplainabilityFactors(debateId: string): Promise<{
    factors: Array<{ name: string; weight: number; description: string; evidence: string[] }>;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/explainability/factors`);
  }

  /**
   * Get natural language narrative explanation.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const narrative = await client.debates.getExplainabilityNarrative('debate-123');
   * console.log(narrative.text);
   * ```
   */
  async getExplainabilityNarrative(debateId: string): Promise<{
    text: string;
    key_points: string[];
    audience_level: string;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/explainability/narrative`);
  }

  /**
   * Get provenance chain for debate claims.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const provenance = await client.debates.getExplainabilityProvenance('debate-123');
   * for (const claim of provenance.claims) {
   *   console.log(`${claim.text}: ${claim.sources.join(', ')}`);
   * }
   * ```
   */
  async getExplainabilityProvenance(debateId: string): Promise<{
    claims: Array<{ text: string; sources: string[]; confidence: number; agent: string }>;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/explainability/provenance`);
  }

  /**
   * Get counterfactual analysis.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const counterfactual = await client.debates.getExplainabilityCounterfactual('debate-123');
   * for (const scenario of counterfactual.scenarios) {
   *   console.log(`If ${scenario.condition}, then ${scenario.outcome}`);
   * }
   * ```
   */
  async getExplainabilityCounterfactual(debateId: string): Promise<{
    scenarios: Array<{ condition: string; outcome: string; probability: number }>;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/explainability/counterfactual`);
  }

  /**
   * Create a counterfactual scenario.
   *
   * @param debateId - The debate ID
   * @param changes - The hypothetical changes to consider
   *
   * @example
   * ```typescript
   * const result = await client.debates.createCounterfactual('debate-123', {
   *   agents: ['claude', 'gpt-4', 'gemini'],
   *   rounds: 5,
   * });
   * console.log(`Counterfactual outcome: ${result.predicted_outcome}`);
   * ```
   */
  async createCounterfactual(
    debateId: string,
    changes: Record<string, unknown>
  ): Promise<{
    predicted_outcome: string;
    confidence: number;
    impact_analysis: Array<{ factor: string; original: unknown; modified: unknown; impact: number }>;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/explainability/counterfactual`, {
      body: changes,
    });
  }

  // ===========================================================================
  // Red Team & Specialized Debates
  // ===========================================================================

  /**
   * Get red team analysis for a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const redTeam = await client.debates.getRedTeam('debate-123');
   * for (const vulnerability of redTeam.vulnerabilities) {
   *   console.log(`${vulnerability.severity}: ${vulnerability.description}`);
   * }
   * ```
   */
  async getRedTeam(debateId: string): Promise<{
    debate_id: string;
    vulnerabilities: Array<{
      severity: 'low' | 'medium' | 'high' | 'critical';
      description: string;
      recommendation: string;
    }>;
    overall_risk: number;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/red-team`);
  }

  /**
   * Run a capability probe debate.
   *
   * @param task - The task to probe
   * @param agents - Optional list of agents to use
   *
   * @example
   * ```typescript
   * const probe = await client.debates.capabilityProbe('Can this system handle real-time data?', ['claude', 'gpt-4']);
   * console.log(`Capability assessment: ${probe.assessment}`);
   * ```
   */
  async capabilityProbe(
    task: string,
    agents?: string[]
  ): Promise<{
    debate_id: string;
    assessment: string;
    capabilities: Array<{ name: string; level: number; evidence: string }>;
    gaps: string[];
  }> {
    const data: { task: string; agents?: string[] } = { task };
    if (agents) {
      data.agents = agents;
    }
    return this.client.request('POST', '/api/v1/debates/capability-probe', {
      body: data,
    });
  }

  /**
   * Run a deep audit debate.
   *
   * @param task - The task to audit
   * @param agents - Optional list of agents to use
   *
   * @example
   * ```typescript
   * const audit = await client.debates.deepAudit('Review the security implementation', ['claude', 'gemini']);
   * console.log(`Audit findings: ${audit.findings.length}`);
   * ```
   */
  async deepAudit(
    task: string,
    agents?: string[]
  ): Promise<{
    debate_id: string;
    findings: Array<{ severity: string; description: string; recommendation: string }>;
    compliance_score: number;
    summary: string;
  }> {
    const data: { task: string; agents?: string[] } = { task };
    if (agents) {
      data.agents = agents;
    }
    return this.client.request('POST', '/api/v1/debates/deep-audit', {
      body: data,
    });
  }

  // ===========================================================================
  // Broadcasting & Publishing
  // ===========================================================================

  /**
   * Broadcast debate to channels.
   *
   * @param debateId - The debate ID
   * @param channels - Optional list of channels to broadcast to
   *
   * @example
   * ```typescript
   * const result = await client.debates.broadcast('debate-123', ['slack', 'discord']);
   * console.log(`Broadcasted to ${result.channels_notified.length} channels`);
   * ```
   */
  async broadcast(
    debateId: string,
    channels?: string[]
  ): Promise<{
    success: boolean;
    channels_notified: string[];
  }> {
    const data: { channels?: string[] } = {};
    if (channels) {
      data.channels = channels;
    }
    return this.client.request('POST', `/api/v1/debates/${debateId}/broadcast`, {
      body: data,
    });
  }

  /**
   * Publish debate summary to Twitter.
   *
   * @param debateId - The debate ID
   * @param message - Optional custom message
   *
   * @example
   * ```typescript
   * const result = await client.debates.publishTwitter('debate-123', 'Check out this debate!');
   * console.log(`Tweet posted: ${result.tweet_id}`);
   * ```
   */
  async publishTwitter(
    debateId: string,
    message?: string
  ): Promise<{
    success: boolean;
    tweet_id?: string;
    url?: string;
  }> {
    const data: { message?: string } = {};
    if (message) {
      data.message = message;
    }
    return this.client.request('POST', `/api/v1/debates/${debateId}/publish/twitter`, {
      body: data,
    });
  }

  /**
   * Publish debate to YouTube.
   *
   * @param debateId - The debate ID
   * @param title - Optional custom title
   *
   * @example
   * ```typescript
   * const result = await client.debates.publishYouTube('debate-123', 'AI Debate: Microservices vs Monolith');
   * console.log(`Video published: ${result.video_id}`);
   * ```
   */
  async publishYouTube(
    debateId: string,
    title?: string
  ): Promise<{
    success: boolean;
    video_id?: string;
    url?: string;
  }> {
    const data: { title?: string } = {};
    if (title) {
      data.title = title;
    }
    return this.client.request('POST', `/api/v1/debates/${debateId}/publish/youtube`, {
      body: data,
    });
  }

  // ===========================================================================
  // Dashboard & History
  // ===========================================================================

  /**
   * Get debates dashboard view.
   *
   * @example
   * ```typescript
   * const dashboard = await client.debates.getDashboard();
   * console.log(`Active debates: ${dashboard.active_count}`);
   * console.log(`Completed today: ${dashboard.completed_today}`);
   * ```
   */
  async getDashboard(): Promise<{
    active_count: number;
    completed_today: number;
    pending_count: number;
    recent_debates: Debate[];
    trending_topics: string[];
  }> {
    return this.client.request('GET', '/api/v1/dashboard/debates');
  }

  /**
   * Get graph stats via the alternate debate endpoint.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const stats = await client.debates.getDebateGraphStats('debate-123');
   * console.log(`Nodes: ${stats.node_count}, Edges: ${stats.edge_count}`);
   * ```
   */
  async getDebateGraphStats(debateId: string): Promise<GraphStats> {
    return this.client.request('GET', `/api/v1/debate/${debateId}/graph-stats`);
  }

  /**
   * Get debate history.
   *
   * @param limit - Maximum number of debates to return (default 20)
   * @param offset - Number of debates to skip (default 0)
   *
   * @example
   * ```typescript
   * const history = await client.debates.getHistory(10, 0);
   * for (const debate of history.debates) {
   *   console.log(`${debate.task}: ${debate.status}`);
   * }
   * ```
   */
  async getHistory(
    limit: number = 20,
    offset: number = 0
  ): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/history/debates', {
      params: { limit, offset },
    });
  }

  // ===========================================================================
  // Pagination & Iteration
  // ===========================================================================

  /**
   * Iterate through all debates with automatic pagination.
   *
   * Returns an async iterator that automatically fetches additional pages
   * as needed. This is useful for processing large numbers of debates
   * without loading them all into memory at once.
   *
   * @param options - Filter and pagination options
   *
   * @example
   * ```typescript
   * // Iterate through all active debates
   * for await (const debate of client.debates.listAll({ status: 'active' })) {
   *   console.log(debate.task);
   * }
   *
   * // Collect all completed debates into an array
   * const paginator = client.debates.listAll({ status: 'completed' });
   * const allCompleted = await paginator.toArray();
   *
   * // Take first 50 debates
   * const first50 = await client.debates.listAll().take(50);
   *
   * // Find a specific debate
   * const found = await client.debates.listAll().find(d => d.task.includes('microservices'));
   * ```
   */
  listAll(options?: {
    status?: string;
    pageSize?: number;
    domain?: string;
    since?: string;
    until?: string;
  }): AsyncPaginator<Debate> {
    const { status, domain, since, until, pageSize = 20 } = options ?? {};

    // Use fromFetch to create a paginator that works with our interface
    const fetchPage = async (params: Record<string, unknown>): Promise<{ data: Debate[] }> => {
      const result = await this.client.listDebates({
        status: (status ?? params.status) as string | undefined,
        limit: (params.limit ?? pageSize) as number | undefined,
        offset: params.offset as number | undefined,
      });
      return { data: result.debates };
    };

    return AsyncPaginator.fromFetch<Debate>(fetchPage, {
      pageSize,
      params: { status, domain, since, until },
    });
  }

  // ===========================================================================
  // Health & Monitoring
  // ===========================================================================

  /**
   * Get health status for debates.
   *
   * Returns monitoring information about debate health including
   * active debates, stuck debates, and system metrics.
   *
   * @example
   * ```typescript
   * const health = await client.debates.listHealth();
   * console.log(`Active debates: ${health.active_count}`);
   * console.log(`Stuck debates: ${health.stuck_count}`);
   * if (health.stuck_debates.length > 0) {
   *   console.log('Stuck debates:', health.stuck_debates);
   * }
   * ```
   */
  async listHealth(): Promise<DebateHealthStatus> {
    return this.client.request('GET', '/api/v1/debates/health');
  }

  /**
   * Get health status for a specific debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const health = await client.debates.getHealth('debate-123');
   * if (health.status === 'stuck') {
   *   console.log(`Debate stuck since round ${health.stuck_since_round}`);
   * }
   * ```
   */
  async getHealth(debateId: string): Promise<DebateHealthDetail> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/health`);
  }

  // ===========================================================================
  // Advanced Query & Filtering
  // ===========================================================================

  /**
   * List debates by date range.
   *
   * @param since - Start date (ISO 8601 format)
   * @param until - End date (ISO 8601 format)
   * @param options - Additional filter options
   *
   * @example
   * ```typescript
   * const debates = await client.debates.listByDateRange(
   *   '2024-01-01T00:00:00Z',
   *   '2024-01-31T23:59:59Z',
   *   { status: 'completed' }
   * );
   * console.log(`${debates.debates.length} debates in January`);
   * ```
   */
  async listByDateRange(
    since: string,
    until: string,
    options?: { status?: string; limit?: number; offset?: number }
  ): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/debates', {
      params: {
        since,
        until,
        ...options,
      },
    });
  }

  /**
   * List debates by status.
   *
   * @param status - The debate status to filter by
   * @param options - Pagination options
   *
   * @example
   * ```typescript
   * const active = await client.debates.listByStatus('running');
   * const completed = await client.debates.listByStatus('completed', { limit: 50 });
   * ```
   */
  async listByStatus(
    status: string,
    options?: { limit?: number; offset?: number }
  ): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/debates', {
      params: {
        status,
        limit: options?.limit ?? 20,
        offset: options?.offset ?? 0,
      },
    });
  }

  /**
   * List debates by participant agent.
   *
   * @param agentName - The agent name to filter by
   * @param options - Additional filter options
   *
   * @example
   * ```typescript
   * const claudeDebates = await client.debates.listByAgent('claude');
   * console.log(`Claude participated in ${claudeDebates.total} debates`);
   * ```
   */
  async listByAgent(
    agentName: string,
    options?: { status?: string; limit?: number; offset?: number }
  ): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/debates', {
      params: {
        agent: agentName,
        ...options,
      },
    });
  }

  /**
   * List debates by domain or topic category.
   *
   * @param domain - The domain to filter by (e.g., 'technology', 'business')
   * @param options - Additional filter options
   *
   * @example
   * ```typescript
   * const techDebates = await client.debates.listByDomain('technology');
   * ```
   */
  async listByDomain(
    domain: string,
    options?: { status?: string; limit?: number; offset?: number }
  ): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/debates', {
      params: {
        domain,
        ...options,
      },
    });
  }

  /**
   * List debates with advanced filtering.
   *
   * @param filters - Advanced filter options
   *
   * @example
   * ```typescript
   * const debates = await client.debates.listWithFilters({
   *   status: 'completed',
   *   agents: ['claude', 'gpt-4'],
   *   minRounds: 3,
   *   consensusReached: true,
   *   since: '2024-01-01',
   *   orderBy: 'created_at',
   *   orderDir: 'desc',
   * });
   * ```
   */
  async listWithFilters(filters: DebateFilters): Promise<{ debates: Debate[]; total: number }> {
    const params: Record<string, unknown> = {};

    if (filters.status) params.status = filters.status;
    if (filters.domain) params.domain = filters.domain;
    if (filters.agents) params.agents = filters.agents.join(',');
    if (filters.minRounds !== undefined) params.min_rounds = filters.minRounds;
    if (filters.maxRounds !== undefined) params.max_rounds = filters.maxRounds;
    if (filters.consensusReached !== undefined) params.consensus_reached = filters.consensusReached;
    if (filters.since) params.since = filters.since;
    if (filters.until) params.until = filters.until;
    if (filters.orderBy) params.order_by = filters.orderBy;
    if (filters.orderDir) params.order_dir = filters.orderDir;
    if (filters.limit !== undefined) params.limit = filters.limit;
    if (filters.offset !== undefined) params.offset = filters.offset;

    return this.client.request('GET', '/api/v1/debates', { params });
  }

  // ===========================================================================
  // Statistics & Analytics
  // ===========================================================================

  /**
   * Get overall debate statistics.
   *
   * @param period - Time period for statistics (e.g., '7d', '30d', '90d')
   *
   * @example
   * ```typescript
   * const stats = await client.debates.getStatistics('30d');
   * console.log(`Total debates: ${stats.total_debates}`);
   * console.log(`Consensus rate: ${stats.consensus_rate}%`);
   * console.log(`Average rounds: ${stats.avg_rounds}`);
   * ```
   */
  async getStatistics(period: string = '30d'): Promise<DebateStatistics> {
    return this.client.request('GET', '/api/v1/debates/statistics', {
      params: { period },
    });
  }

  /**
   * Get debate statistics using the compatibility route.
   */
  async getStats(period: string = 'all'): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/debates/stats', {
      params: { period },
    });
  }

  /**
   * Get per-agent debate statistics using the compatibility route.
   */
  async getStatsAgents(limit: number = 20): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/debates/stats/agents', {
      params: { limit },
    });
  }

  /**
   * Get agent performance statistics across debates.
   *
   * @param options - Filter options
   *
   * @example
   * ```typescript
   * const agentStats = await client.debates.getAgentStatistics({ period: '30d' });
   * for (const agent of agentStats.agents) {
   *   console.log(`${agent.name}: ${agent.win_rate}% win rate`);
   * }
   * ```
   */
  async getAgentStatistics(options?: {
    period?: string;
    agents?: string[];
  }): Promise<DebateAgentStatistics> {
    return this.client.request('GET', '/api/v1/debates/statistics/agents', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Get consensus analytics for debates.
   *
   * @param period - Time period for analytics
   *
   * @example
   * ```typescript
   * const consensus = await client.debates.getConsensusAnalytics('30d');
   * console.log(`Consensus reached in ${consensus.reached_count}/${consensus.total_debates}`);
   * console.log(`Average confidence: ${consensus.avg_confidence}`);
   * ```
   */
  async getConsensusAnalytics(period: string = '30d'): Promise<ConsensusAnalytics> {
    return this.client.request('GET', '/api/v1/debates/analytics/consensus', {
      params: { period },
    });
  }

  /**
   * Get topic trends in debates.
   *
   * @param options - Filter options
   *
   * @example
   * ```typescript
   * const trends = await client.debates.getTopicTrends({ period: '7d', limit: 10 });
   * for (const topic of trends.topics) {
   *   console.log(`${topic.name}: ${topic.count} debates, ${topic.velocity} trend`);
   * }
   * ```
   */
  async getTopicTrends(options?: {
    period?: string;
    limit?: number;
  }): Promise<TopicTrends> {
    return this.client.request('GET', '/api/v1/debates/analytics/trends', {
      params: options as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Import & Export
  // ===========================================================================

  /**
   * Import a debate from an external format.
   *
   * @param data - The debate data to import
   * @param format - The format of the imported data
   *
   * @example
   * ```typescript
   * const imported = await client.debates.importDebate(
   *   jsonContent,
   *   'json'
   * );
   * console.log(`Imported debate: ${imported.debate_id}`);
   * ```
   */
  async importDebate(
    data: string,
    format: 'json' | 'markdown' = 'json'
  ): Promise<{ debate_id: string; success: boolean }> {
    return this.client.request('POST', '/api/v1/debates/import', {
      body: { data, format },
    });
  }

  /**
   * Export multiple debates in a batch.
   *
   * @param debateIds - Array of debate IDs to export
   * @param format - Export format
   *
   * @example
   * ```typescript
   * const exported = await client.debates.exportBatch(
   *   ['debate-1', 'debate-2', 'debate-3'],
   *   'json'
   * );
   * console.log(`Exported ${exported.count} debates`);
   * ```
   */
  async exportBatch(
    debateIds: string[],
    format: 'json' | 'markdown' | 'html' | 'pdf' = 'json'
  ): Promise<BatchExportResult> {
    return this.client.request('POST', '/api/v1/debates/export/batch', {
      body: { debate_ids: debateIds, format },
    });
  }

  // ===========================================================================
  // Batch Operations (Extended)
  // ===========================================================================

  /**
   * Cancel a batch job.
   *
   * @param batchId - The batch ID to cancel
   *
   * @example
   * ```typescript
   * const result = await client.debates.cancelBatch('batch-123');
   * if (result.success) {
   *   console.log(`Batch cancelled: ${result.cancelled_jobs} jobs stopped`);
   * }
   * ```
   */
  async cancelBatch(batchId: string): Promise<{ success: boolean; cancelled_jobs: number }> {
    return this.client.request('POST', `/api/v1/debates/batch/${batchId}/cancel`);
  }

  /**
   * Retry failed jobs in a batch.
   *
   * @param batchId - The batch ID
   * @param options - Retry options
   *
   * @example
   * ```typescript
   * const result = await client.debates.retryBatch('batch-123', { onlyFailed: true });
   * console.log(`Retrying ${result.retried_count} jobs`);
   * ```
   */
  async retryBatch(
    batchId: string,
    options?: { onlyFailed?: boolean }
  ): Promise<{ success: boolean; retried_count: number }> {
    return this.client.request('POST', `/api/v1/debates/batch/${batchId}/retry`, {
      body: options,
    });
  }

  /**
   * Get detailed results from a completed batch.
   *
   * @param batchId - The batch ID
   *
   * @example
   * ```typescript
   * const results = await client.debates.getBatchResults('batch-123');
   * for (const result of results.debates) {
   *   console.log(`${result.debate_id}: ${result.status}`);
   * }
   * ```
   */
  async getBatchResults(batchId: string): Promise<BatchResults> {
    return this.client.request('GET', `/api/v1/debates/batch/${batchId}/results`);
  }

  // ===========================================================================
  // Comparison & Analysis
  // ===========================================================================

  /**
   * Compare multiple debates.
   *
   * @param debateIds - Array of debate IDs to compare
   *
   * @example
   * ```typescript
   * const comparison = await client.debates.compare(['debate-1', 'debate-2']);
   * console.log(`Similarity: ${comparison.similarity_score}`);
   * console.log('Common themes:', comparison.common_themes);
   * console.log('Divergent points:', comparison.divergent_points);
   * ```
   */
  async compare(debateIds: string[]): Promise<DebateComparison> {
    return this.client.request('POST', '/api/v1/debates/compare', {
      body: { debate_ids: debateIds },
    });
  }

  /**
   * Get similar debates to a given debate.
   *
   * @param debateId - The debate ID to find similar debates for
   * @param limit - Maximum number of similar debates to return
   *
   * @example
   * ```typescript
   * const similar = await client.debates.findSimilar('debate-123', 5);
   * for (const debate of similar.debates) {
   *   console.log(`${debate.debate_id}: ${debate.similarity_score}`);
   * }
   * ```
   */
  async findSimilar(
    debateId: string,
    limit: number = 10
  ): Promise<{ debates: Array<{ debate_id: string; similarity_score: number; task: string }> }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/similar`, {
      params: { limit },
    });
  }

  /**
   * Analyze argument quality in a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const quality = await client.debates.analyzeArgumentQuality('debate-123');
   * console.log(`Overall quality: ${quality.overall_score}`);
   * for (const agent of quality.by_agent) {
   *   console.log(`${agent.name}: ${agent.quality_score}`);
   * }
   * ```
   */
  async analyzeArgumentQuality(debateId: string): Promise<ArgumentQualityAnalysis> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/quality`);
  }

  // ===========================================================================
  // Archival & Cleanup
  // ===========================================================================

  /**
   * Archive multiple debates in batch.
   *
   * @param debateIds - Array of debate IDs to archive
   *
   * @example
   * ```typescript
   * const result = await client.debates.archiveBatch(['debate-1', 'debate-2']);
   * console.log(`Archived ${result.archived_count} debates`);
   * ```
   */
  async archiveBatch(debateIds: string[]): Promise<{ success: boolean; archived_count: number }> {
    return this.client.request('POST', '/api/v1/debates/archive/batch', {
      body: { debate_ids: debateIds },
    });
  }

  /**
   * List archived debates.
   *
   * @param options - Pagination options
   *
   * @example
   * ```typescript
   * const archived = await client.debates.listArchived({ limit: 50 });
   * console.log(`${archived.total} debates in archive`);
   * ```
   */
  async listArchived(options?: {
    limit?: number;
    offset?: number;
  }): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/debates/archived', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Restore an archived debate.
   *
   * @param debateId - The debate ID to restore
   *
   * @example
   * ```typescript
   * const result = await client.debates.restore('debate-123');
   * if (result.success) {
   *   console.log('Debate restored successfully');
   * }
   * ```
   */
  async restore(debateId: string): Promise<{ success: boolean }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/restore`);
  }

  /**
   * Permanently delete a debate (requires archive first).
   *
   * @param debateId - The debate ID to delete permanently
   *
   * @example
   * ```typescript
   * const result = await client.debates.deletePermanently('debate-123');
   * if (result.success) {
   *   console.log('Debate permanently deleted');
   * }
   * ```
   */
  async deletePermanently(debateId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/v1/debates/${debateId}/permanent`);
  }

  // ===========================================================================
  // Tags & Metadata
  // ===========================================================================

  /**
   * Add tags to a debate.
   *
   * @param debateId - The debate ID
   * @param tags - Array of tags to add
   *
   * @example
   * ```typescript
   * await client.debates.addTags('debate-123', ['important', 'review']);
   * ```
   */
  async addTags(debateId: string, tags: string[]): Promise<{ success: boolean; tags: string[] }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/tags`, {
      body: { tags },
    });
  }

  /**
   * Remove tags from a debate.
   *
   * @param debateId - The debate ID
   * @param tags - Array of tags to remove
   *
   * @example
   * ```typescript
   * await client.debates.removeTags('debate-123', ['review']);
   * ```
   */
  async removeTags(debateId: string, tags: string[]): Promise<{ success: boolean; tags: string[] }> {
    return this.client.request('DELETE', `/api/v1/debates/${debateId}/tags`, {
      body: { tags },
    });
  }

  /**
   * List debates by tag.
   *
   * @param tag - The tag to filter by
   * @param options - Pagination options
   *
   * @example
   * ```typescript
   * const tagged = await client.debates.listByTag('important');
   * ```
   */
  async listByTag(
    tag: string,
    options?: { limit?: number; offset?: number }
  ): Promise<{ debates: Debate[]; total: number }> {
    return this.client.request('GET', '/api/v1/debates', {
      params: {
        tag,
        ...options,
      },
    });
  }

  /**
   * Update metadata for a debate.
   *
   * @param debateId - The debate ID
   * @param metadata - Metadata to merge with existing metadata
   *
   * @example
   * ```typescript
   * await client.debates.updateMetadata('debate-123', {
   *   priority: 'high',
   *   reviewer: 'john@example.com',
   * });
   * ```
   */
  async updateMetadata(
    debateId: string,
    metadata: Record<string, unknown>
  ): Promise<{ success: boolean; metadata: Record<string, unknown> }> {
    return this.client.request('PATCH', `/api/v1/debates/${debateId}/metadata`, {
      body: { metadata },
    });
  }

  // ===========================================================================
  // Notes & Comments
  // ===========================================================================

  /**
   * Add a note to a debate.
   *
   * @param debateId - The debate ID
   * @param note - The note content
   *
   * @example
   * ```typescript
   * const result = await client.debates.addNote('debate-123', 'Needs further review');
   * console.log(`Note added: ${result.note_id}`);
   * ```
   */
  async addNote(
    debateId: string,
    note: string
  ): Promise<{ note_id: string; success: boolean }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/notes`, {
      body: { note },
    });
  }

  /**
   * Get notes for a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const notes = await client.debates.getNotes('debate-123');
   * for (const note of notes) {
   *   console.log(`${note.created_at}: ${note.content}`);
   * }
   * ```
   */
  async getNotes(debateId: string): Promise<DebateNote[]> {
    const response = await this.client.request<{ notes: DebateNote[] }>(
      'GET',
      `/api/v1/debates/${debateId}/notes`
    );
    return response.notes;
  }

  /**
   * Delete a note from a debate.
   *
   * @param debateId - The debate ID
   * @param noteId - The note ID to delete
   *
   * @example
   * ```typescript
   * await client.debates.deleteNote('debate-123', 'note-456');
   * ```
   */
  async deleteNote(debateId: string, noteId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/v1/debates/${debateId}/notes/${noteId}`);
  }

  // ===========================================================================
  // Streaming
  // ===========================================================================

  /**
   * Stream debate events via Server-Sent Events.
   *
   * Returns an SSE stream of real-time debate events including
   * debate_started, round_start, agent_message, consensus, and debate_end.
   *
   * @example
   * ```typescript
   * const stream = await client.debates.streamDebates();
   * console.log('Connected to debate event stream');
   * ```
   */
  async streamDebates(): Promise<unknown> {
    return this.client.request('GET', '/api/v1/debates/stream');
  }

  // ===========================================================================
  // RLM / Compression
  // ===========================================================================

  /**
   * Compress debate context using RLM hierarchical abstraction.
   *
   * Creates compressed representations of the debate at multiple
   * abstraction levels for efficient querying.
   *
   * @param debateId - The debate ID
   * @param options - Compression options
   *
   * @example
   * ```typescript
   * const result = await client.debates.compress('debate-123', {
   *   targetLevels: ['ABSTRACT', 'SUMMARY', 'DETAILED'],
   *   compressionRatio: 0.3,
   * });
   * console.log(`Original: ${result.original_tokens} tokens`);
   * console.log(`Compressed: ${JSON.stringify(result.compressed_tokens)}`);
   * ```
   */
  async compress(
    debateId: string,
    options?: {
      targetLevels?: string[];
      compressionRatio?: number;
    }
  ): Promise<{
    original_tokens: number;
    compressed_tokens: Record<string, number>;
    compression_ratios: Record<string, number>;
    time_seconds: number;
    levels_created: number;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/compress`, {
      body: {
        target_levels: options?.targetLevels,
        compression_ratio: options?.compressionRatio ?? 0.3,
      },
    });
  }

  /**
   * Get debate content at a specific abstraction level.
   *
   * Returns the debate context compressed to the requested level
   * of abstraction (ABSTRACT, SUMMARY, DETAILED, or RAW).
   *
   * @param debateId - The debate ID
   * @param level - Abstraction level
   *
   * @example
   * ```typescript
   * const context = await client.debates.getContextLevel('debate-123', 'SUMMARY');
   * console.log(`Level: ${context.level}, Tokens: ${context.token_count}`);
   * console.log(context.content);
   * ```
   */
  async getContextLevel(
    debateId: string,
    level: 'ABSTRACT' | 'SUMMARY' | 'DETAILED' | 'RAW'
  ): Promise<{
    level: string;
    content: string;
    token_count: number;
    nodes: Array<{
      id: string;
      content: string;
      token_count: number;
      key_topics: string[];
    }>;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/context/${level}`);
  }

  /**
   * Query a debate using RLM with iterative refinement.
   *
   * Asks a question about a debate and uses RLM to find the answer
   * by iteratively refining through abstraction levels.
   *
   * @param debateId - The debate ID
   * @param query - The question to ask about the debate
   * @param options - Query options
   *
   * @example
   * ```typescript
   * const result = await client.debates.queryRlm('debate-123', 'What was the consensus on pricing?', {
   *   strategy: 'auto',
   *   maxIterations: 3,
   * });
   * console.log(`Answer: ${result.answer}`);
   * console.log(`Confidence: ${result.confidence}`);
   * ```
   */
  async queryRlm(
    debateId: string,
    query: string,
    options?: {
      strategy?: 'auto' | 'peek' | 'grep' | 'partition_map' | 'summarize' | 'hierarchical';
      maxIterations?: number;
      startLevel?: 'ABSTRACT' | 'SUMMARY' | 'DETAILED' | 'RAW';
    }
  ): Promise<{
    answer: string;
    ready: boolean;
    iteration: number;
    refinement_history: unknown[];
    confidence: number;
    nodes_examined: unknown[];
    tokens_processed: number;
    sub_calls_made: number;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/query-rlm`, {
      body: {
        query,
        strategy: options?.strategy ?? 'auto',
        max_iterations: options?.maxIterations ?? 3,
        start_level: options?.startLevel ?? 'SUMMARY',
      },
    });
  }

  /**
   * Get the status of an ongoing RLM refinement process.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const status = await client.debates.getRefinementStatus('debate-123');
   * console.log(`Status: ${status.status}, Active queries: ${status.active_queries}`);
   * ```
   */
  async getRefinementStatus(debateId: string): Promise<{
    debate_id: string;
    active_queries: number;
    cached_contexts: number;
    status: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/refinement-status`);
  }

  // ===========================================================================
  // Decision Integrity
  // ===========================================================================

  /**
   * Get the decision integrity package for a debate.
   *
   * Generates a decision receipt and implementation plan bundle
   * containing audit-ready documentation of the debate outcome.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const pkg = await client.debates.getDecisionIntegrity('debate-123');
   * console.log(`Receipt: ${pkg.receipt_id}`);
   * console.log(`Plan steps: ${pkg.implementation_plan?.steps?.length}`);
   * ```
   */
  async getDecisionIntegrity(debateId: string): Promise<{
    receipt_id: string;
    debate_id: string;
    receipt: Record<string, unknown>;
    implementation_plan: Record<string, unknown>;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/decision-integrity`);
  }

  /**
   * Get decision package JSON using the compatibility route.
   */
  async getPackage(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/package`
    );
  }

  /**
   * Get decision package markdown using the compatibility route.
   */
  async getPackageMarkdown(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/package/markdown`
    );
  }

  /**
   * Enable public sharing for a debate.
   */
  async share(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'POST',
      `/api/debates/${encodeURIComponent(debateId)}/share`
    );
  }

  /**
   * Revoke public sharing for a debate.
   */
  async revokeShare(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'POST',
      `/api/debates/${encodeURIComponent(debateId)}/share/revoke`
    );
  }

  /**
   * Get public spectate status for a shared debate.
   */
  async getPublicSpectate(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/spectate/public`
    );
  }

  /**
   * Get diagnostics for a debate.
   */
  async getDiagnostics(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/diagnostics`
    );
  }

  /**
   * Get per-debate cost breakdown.
   *
   * Returns detailed cost data including total cost, per-agent costs,
   * per-round costs, and model usage for a specific debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const costs = await client.debates.getDebateCosts('debate-123');
   * console.log(`Total cost: $${costs.total_cost}`);
   * ```
   */
  async getDebateCosts(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/costs`
    );
  }

  /**
   * Get polling fallback events for a debate.
   *
   * Returns missed or recent events for clients that cannot use
   * WebSocket streaming. Supports pagination via query params.
   *
   * @param debateId - The debate ID
   * @param options - Optional pagination and filtering
   *
   * @example
   * ```typescript
   * const events = await client.debates.getDebateEvents('debate-123', { since: '2026-01-01' });
   * for (const event of events.events) {
   *   console.log(`${event.type}: ${event.data}`);
   * }
   * ```
   */
  async getDebateEvents(
    debateId: string,
    options?: { since?: string; limit?: number; offset?: number }
  ): Promise<Record<string, unknown>> {
    const params: Record<string, unknown> = {};
    if (options?.since) params.since = options.since;
    if (options?.limit !== undefined) params.limit = options.limit;
    if (options?.offset !== undefined) params.offset = options.offset;
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/events`,
      { params }
    );
  }

  /**
   * Get per-agent position evolution for a debate.
   *
   * Returns how each agent's position changed across rounds,
   * useful for understanding convergence patterns.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const positions = await client.debates.getPositions('debate-123');
   * for (const [agent, rounds] of Object.entries(positions.positions)) {
   *   console.log(`${agent}: ${rounds}`);
   * }
   * ```
   */
  async getPositions(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'GET',
      `/api/debates/${encodeURIComponent(debateId)}/positions`
    );
  }

  // ===========================================================================
  // Intervention
  // ===========================================================================

  /**
   * Inject a user argument or follow-up question into a debate.
   *
   * The injected content will be included in the next round's context
   * and considered by all agents.
   *
   * @param debateId - The active debate ID
   * @param content - The argument or question to inject
   * @param options - Injection options
   *
   * @example
   * ```typescript
   * const result = await client.debates.interventionInject('debate-123', 'Consider the cost implications', {
   *   type: 'argument',
   *   source: 'user',
   * });
   * console.log(`Injected: ${result.injection_id}, appears in: ${result.will_appear_in}`);
   * ```
   */
  async interventionInject(
    debateId: string,
    content: string,
    options?: {
      type?: 'argument' | 'follow_up';
      source?: string;
    }
  ): Promise<{
    success: boolean;
    debate_id: string;
    injection_id: string;
    type: string;
    message: string;
    will_appear_in: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/intervention/inject`, {
      body: {
        content,
        type: options?.type ?? 'argument',
        source: options?.source ?? 'user',
      },
    });
  }

  /**
   * Get the intervention audit log for a debate.
   *
   * Returns all interventions with timestamps for compliance and audit purposes.
   *
   * @param debateId - The debate ID
   * @param limit - Maximum number of log entries to return (default 50)
   *
   * @example
   * ```typescript
   * const log = await client.debates.interventionLog('debate-123');
   * console.log(`Total interventions: ${log.total_interventions}`);
   * for (const entry of log.interventions) {
   *   console.log(`${entry.timestamp}: ${entry.type}`);
   * }
   * ```
   */
  async interventionLog(
    debateId: string,
    limit: number = 50
  ): Promise<{
    debate_id: string;
    total_interventions: number;
    interventions: Array<{
      timestamp: string;
      debate_id: string;
      type: string;
      data: Record<string, unknown>;
      user_id: string | null;
    }>;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/intervention/log`, {
      params: { limit },
    });
  }

  /**
   * Pause an active debate.
   *
   * Pausing stops agent responses but preserves all debate state.
   * The debate can be resumed at any point.
   *
   * @param debateId - The active debate ID
   *
   * @example
   * ```typescript
   * const result = await client.debates.interventionPause('debate-123');
   * if (result.success) {
   *   console.log(`Debate paused at ${result.paused_at}`);
   * }
   * ```
   */
  async interventionPause(debateId: string): Promise<{
    success: boolean;
    debate_id: string;
    is_paused: boolean;
    paused_at: string;
    message: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/intervention/pause`);
  }

  /**
   * Resume a paused debate.
   *
   * Resumes agent responses from where they left off.
   *
   * @param debateId - The paused debate ID
   *
   * @example
   * ```typescript
   * const result = await client.debates.interventionResume('debate-123');
   * if (result.success) {
   *   console.log(`Debate resumed at ${result.resumed_at}`);
   *   console.log(`Was paused for ${result.pause_duration_seconds}s`);
   * }
   * ```
   */
  async interventionResume(debateId: string): Promise<{
    success: boolean;
    debate_id: string;
    is_paused: boolean;
    resumed_at: string;
    pause_duration_seconds: number | null;
    message: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/intervention/resume`);
  }

  /**
   * Get the current intervention state for a debate.
   *
   * Returns pause status, agent weights, consensus threshold,
   * and counts of pending injections and follow-ups.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const state = await client.debates.interventionState('debate-123');
   * console.log(`Paused: ${state.is_paused}`);
   * console.log(`Threshold: ${state.consensus_threshold}`);
   * console.log(`Pending injections: ${state.pending_injections}`);
   * ```
   */
  async interventionState(debateId: string): Promise<{
    debate_id: string;
    is_paused: boolean;
    paused_at: string | null;
    consensus_threshold: number;
    agent_weights: Record<string, number>;
    pending_injections: number;
    pending_follow_ups: number;
  }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/intervention/state`);
  }

  /**
   * Update the consensus threshold for a debate.
   *
   * Threshold is the minimum agreement level required for consensus:
   * 0.5 = simple majority, 0.75 = strong majority (default), 1.0 = unanimous.
   *
   * @param debateId - The active debate ID
   * @param threshold - New threshold value (0.5 to 1.0)
   *
   * @example
   * ```typescript
   * const result = await client.debates.interventionUpdateThreshold('debate-123', 0.8);
   * console.log(`Threshold changed from ${result.old_threshold} to ${result.new_threshold}`);
   * ```
   */
  async interventionUpdateThreshold(
    debateId: string,
    threshold: number
  ): Promise<{
    success: boolean;
    debate_id: string;
    old_threshold: number;
    new_threshold: number;
    message: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/intervention/threshold`, {
      body: { threshold },
    });
  }

  /**
   * Update an agent's influence weight in a debate.
   *
   * Weight affects how much the agent's vote counts in consensus:
   * 0.0 = muted, 1.0 = normal influence, 2.0 = double influence.
   *
   * @param debateId - The active debate ID
   * @param agent - Agent name or ID
   * @param weight - New weight value (0.0 to 2.0)
   *
   * @example
   * ```typescript
   * const result = await client.debates.interventionUpdateWeights('debate-123', 'claude', 1.5);
   * console.log(`${result.agent} weight: ${result.old_weight} -> ${result.new_weight}`);
   * ```
   */
  async interventionUpdateWeights(
    debateId: string,
    agent: string,
    weight: number
  ): Promise<{
    success: boolean;
    debate_id: string;
    agent: string;
    old_weight: number;
    new_weight: number;
    message: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/intervention/weights`, {
      body: { agent, weight },
    });
  }

  /**
   * List debates.
   */
  async listDebates(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/debate', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Estimate the cost of a debate before creation.
   */
  async estimateCost(options?: {
    numAgents?: number;
    numRounds?: number;
    modelTypes?: string[];
  }): Promise<{
    total_estimated_cost: number;
    per_model_breakdown: Record<string, unknown>[];
    assumptions: Record<string, unknown>;
    currency: string;
  }> {
    const params: Record<string, unknown> = {};
    if (options?.numAgents !== undefined) params.num_agents = options.numAgents;
    if (options?.numRounds !== undefined) params.num_rounds = options.numRounds;
    if (options?.modelTypes) params.model_types = options.modelTypes.join(',');
    return this.client.request('GET', '/api/v1/debates/estimate-cost', {
      params,
    }) as Promise<{
      total_estimated_cost: number;
      per_model_breakdown: Record<string, unknown>[];
      assumptions: Record<string, unknown>;
      currency: string;
    }>;
  }

  // ===========================================================================
  // One-Click Debate
  // ===========================================================================

  /**
   * One-click debate launcher.
   *
   * Convenience endpoint for quick debate creation. Only requires a
   * question; auto-detects format based on question length and
   * auto-selects agents.
   *
   * @param question - The topic to debate
   * @param options - Optional context and source
   *
   * @example
   * ```typescript
   * const result = await client.debates.debateThis('Should we adopt Kubernetes?');
   * console.log(`Debate created: ${result.debate_id}`);
   * console.log(`Spectate: ${result.spectate_url}`);
   * ```
   */
  async debateThis(
    question: string,
    options?: { context?: string; source?: string }
  ): Promise<{
    debate_id: string;
    spectate_url?: string;
  }> {
    const body: Record<string, unknown> = { question };
    if (options?.context) body.context = options.context;
    if (options?.source) body.source = options.source;
    return this.client.request('POST', '/api/v1/debate-this', { body });
  }

  /**
   * View a publicly shared debate by its share token.
   *
   * @param shareToken - The share token from the shared URL
   */
  async getShared(shareToken: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/shared/${encodeURIComponent(shareToken)}`);
  }

  // ===========================================================================
  // Mid-Debate Intervention
  // ===========================================================================

  /**
   * Submit a mid-debate intervention.
   *
   * Allows a user to inject a redirect, constraint, challenge, or evidence
   * request into a running debate. The intervention is queued and applied
   * at the specified round (or the next available round).
   *
   * @param debateId - The active debate ID
   * @param options - Intervention details
   *
   * @example
   * ```typescript
   * const result = await client.debates.intervene('debate-123', {
   *   type: 'redirect',
   *   content: 'Consider the security implications',
   * });
   * console.log(`Intervention ${result.intervention_id} queued for round ${result.apply_at_round}`);
   * ```
   */
  async intervene(
    debateId: string,
    options: {
      type: 'redirect' | 'constraint' | 'challenge' | 'evidence_request';
      content: string;
      apply_at_round?: number;
      user_id?: string;
      metadata?: Record<string, unknown>;
    }
  ): Promise<{
    intervention_id: string;
    status: string;
    apply_at_round: number;
    type: string;
    debate_id: string;
  }> {
    return this.client.request('POST', `/api/v1/debates/${encodeURIComponent(debateId)}/intervene`, {
      body: options,
    });
  }

  /**
   * Get per-agent reasoning summary for a debate.
   *
   * Returns reasoning chains, key crux points, unresolved disagreements,
   * and intervention data for a debate.
   *
   * @param debateId - The debate ID
   *
   * @example
   * ```typescript
   * const reasoning = await client.debates.getReasoning('debate-123');
   * for (const agent of reasoning.agents) {
   *   console.log(`${agent.name}: confidence ${agent.confidence}`);
   * }
   * for (const crux of reasoning.cruxes) {
   *   console.log(`Crux: ${crux.claim} (confidence: ${crux.confidence})`);
   * }
   * ```
   */
  async getReasoning(debateId: string): Promise<{
    data: {
      debate_id: string;
      agents: Array<{
        name: string;
        role: string;
        last_position: string;
        confidence: number;
      }>;
      cruxes: Array<{
        claim?: string;
        confidence?: number;
        contested_by?: string[];
      }>;
      unresolved_disagreements: unknown[];
      interventions: Record<string, unknown>;
    };
  }> {
    return this.client.request('GET', `/api/v1/debates/${encodeURIComponent(debateId)}/reasoning`);
  }
  /**
   * Get per-agent performance statistics for a specific debate.
   *
   * @param debateId - The debate to retrieve agent statistics for
   * @returns Per-agent statistics keyed by agent name
   *
   * @example
   * ```typescript
   * const stats = await client.debates.getDebateAgentStatistics('debate-123');
   * for (const [agent, data] of Object.entries(stats.agents)) {
   *   console.log(`${agent}: score=${data.contribution_score}`);
   * }
   * ```
   */
  async getDebateAgentStatistics(debateId: string): Promise<{
    debate_id: string;
    agents: Record<string, {
      contribution_score?: number;
      argument_count?: number;
      consensus_alignment?: number;
      win_rate?: number;
      avg_confidence?: number;
    }>;
  }> {
    return this.client.request('GET', `/api/v1/debates/${encodeURIComponent(debateId)}/agent-statistics`);
  }

  /**
   * Make a debate permanent (prevent automatic cleanup or archiving).
   *
   * @param debateId - The debate to mark as permanent
   *
   * @example
   * ```typescript
   * const result = await client.debates.makePermanent('debate-123');
   * console.log(`Debate is now permanent: ${result.is_permanent}`);
   * ```
   */
  async makePermanent(debateId: string): Promise<{ success: boolean; is_permanent: boolean; debate_id: string }> {
    return this.client.request('POST', `/api/v1/debates/${encodeURIComponent(debateId)}/make-permanent`);
  }
}
