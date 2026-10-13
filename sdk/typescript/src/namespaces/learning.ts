/**
 * Learning Namespace API
 *
 * Provides access to learning cycles, patterns, agent evolution, and insights.
 */

export interface LearningCycle {
  cycle_id: string;
  started_at: string;
  completed_at?: string;
  debates_analyzed: number;
  patterns_found: number;
  summary?: string;
}

export interface LearnedPattern {
  id: string;
  pattern_type: string;
  description: string;
  confidence: number;
  frequency: number;
  first_seen: string;
  last_seen: string;
  metadata?: Record<string, unknown>;
}

export interface AgentEvolution {
  agent: string;
  timeline: Array<{
    timestamp: string;
    elo_rating?: number;
    calibration_score?: number;
    debate_count?: number;
    win_rate?: number;
  }>;
  trend?: 'improving' | 'stable' | 'declining';
}

export interface LearningInsight {
  id: string;
  type: string;
  description: string;
  confidence: number;
  source_cycles: string[];
  created_at: string;
}

export interface LearningEvolutionResponse {
  summary?: Record<string, unknown>;
  timeline?: Array<Record<string, unknown>>;
  patterns?: LearnedPattern[];
}

interface LearningClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown> }
  ): Promise<T>;
}

export class LearningAPI {
  constructor(private client: LearningClientInterface) {}

  /**
   * Get all learning cycle summaries.
   */
  async getCycles(params?: {
    limit?: number;
    offset?: number;
  }): Promise<{ cycles: LearningCycle[]; total?: number }> {
    return this.client.request('GET', '/api/v1/learning/cycles', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get learned patterns across cycles.
   */
  async getPatterns(params?: {
    pattern_type?: string;
    min_confidence?: number;
    limit?: number;
  }): Promise<{ patterns: LearnedPattern[]; total?: number }> {
    return this.client.request('GET', '/api/v1/learning/patterns', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get agent performance evolution over time.
   */
  async getAgentEvolution(params?: {
    agents?: string[];
    period?: string;
  }): Promise<{ agents: AgentEvolution[] }> {
    return this.client.request('GET', '/api/v1/learning/agent-evolution', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get aggregated insights from learning cycles.
   */
  async getInsights(params?: {
    limit?: number;
  }): Promise<{ insights: LearningInsight[] }> {
    return this.client.request('GET', '/api/v1/learning/insights', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get meta-learning evolution patterns.
   */
  async getEvolution(): Promise<LearningEvolutionResponse> {
    return this.client.request('GET', '/api/v1/learning/evolution');
  }

  // ===========================================================================
  // Training Sessions (v2 Autonomous Learning)
  // ===========================================================================

  /**
   * List training sessions with optional filtering.
   */
  async listSessions(params?: {
    status?: string;
    mode?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ sessions: Record<string, unknown>[]; pagination: Record<string, unknown> }> {
    return this.client.request('POST', '/api/v1/learning/sessions', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get a specific training session by ID.
   */
  async getSession(sessionId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/learning/sessions/${sessionId}`);
  }

  /**
   * Create a new training session.
   */
  async createSession(body: {
    name: string;
    mode?: string;
    total_epochs?: number;
    config?: Record<string, unknown>;
  }): Promise<{ session: Record<string, unknown>; message: string }> {
    return this.client.request('POST', '/api/v1/learning/sessions', {
      params: body as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Metrics
  // ===========================================================================

  /**
   * Get learning metrics with filtering.
   */
  async getMetrics(params?: {
    session_id?: string;
    agent_id?: string;
    limit?: number;
  }): Promise<{ metrics: Record<string, unknown>[]; count: number }> {
    return this.client.request('POST', '/api/v1/learning/metrics', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get metrics of a specific type with aggregations.
   */
  async getMetricByType(metricType: string): Promise<{
    metric_type: string;
    count: number;
    average: number;
    min: number;
    max: number;
    recent: Record<string, unknown>[];
  }> {
    return this.client.request('GET', `/api/v1/learning/metrics/${metricType}`);
  }

  // ===========================================================================
  // Feedback
  // ===========================================================================

  /**
   * Submit feedback on learning outcomes.
   */
  async submitFeedback(body: {
    feedback_type: string;
    target_type: string;
    target_id: string;
    comment?: string;
    rating?: number;
  }): Promise<{ feedback: Record<string, unknown>; message: string }> {
    return this.client.request('POST', '/api/v1/learning/feedback', {
      params: body as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Pattern Details
  // ===========================================================================

  /**
   * Get a specific pattern by ID.
   */
  async getPattern(patternId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/learning/patterns/${patternId}`);
  }

  // ===========================================================================
  // Knowledge
  // ===========================================================================

  /**
   * List extracted knowledge items.
   */
  async listKnowledge(params?: {
    verified?: boolean;
    source_type?: string;
    limit?: number;
  }): Promise<{ knowledge: Record<string, unknown>[]; count: number }> {
    return this.client.request('POST', '/api/v1/learning/knowledge', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get a specific knowledge item by ID.
   */
  async getKnowledgeItem(knowledgeId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/learning/knowledge/${knowledgeId}`);
  }

  /**
   * Trigger knowledge extraction from debates.
   */
  async extractKnowledge(body: {
    debate_ids: string[];
    title?: string;
    content?: string;
    topics?: string[];
  }): Promise<{ knowledge: Record<string, unknown>; message: string }> {
    return this.client.request('POST', '/api/v1/learning/knowledge/extract', {
      params: body as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Recommendations and Performance
  // ===========================================================================

  /**
   * Get learning recommendations.
   */
  async getRecommendations(params?: {
    limit?: number;
  }): Promise<{ recommendations: Record<string, unknown>[]; count: number }> {
    return this.client.request('POST', '/api/v1/learning/recommendations', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get model performance statistics.
   */
  async getPerformance(): Promise<{ performance: Record<string, unknown> }> {
    return this.client.request('POST', '/api/v1/learning/performance');
  }

  /**
   * Trigger model calibration.
   */
  async calibrate(body?: {
    agent_ids?: string[];
    force?: boolean;
  }): Promise<{ calibration_id: string; metric: Record<string, unknown>; message: string }> {
    return this.client.request('POST', '/api/v1/learning/calibrate', {
      params: body as Record<string, unknown>,
    });
  }
}
