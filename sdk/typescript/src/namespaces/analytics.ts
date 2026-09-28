/**
 * Analytics Namespace API
 *
 * Provides a namespaced interface for analytics and metrics operations.
 * This wraps the flat client methods for a more intuitive API.
 */

import type {
  DisagreementAnalytics,
  RoleRotationAnalytics,
  EarlyStopAnalytics,
  ConsensusQualityAnalytics,
  RankingStats,
  MemoryStats,
} from '../types';

/**
 * Period options for analytics queries.
 */
export interface AnalyticsPeriodOptions {
  /** Time period (e.g., '7d', '30d', '90d') */
  period?: string;
}

/**
 * Options for decision analytics queries.
 */
export interface DecisionAnalyticsPeriodOptions extends Record<string, unknown> {
  /** Time period (e.g., '24h', '7d', '30d', '90d') */
  period?: string;
}

/**
 * Options for paginated decision outcomes.
 */
export interface DecisionAnalyticsOutcomesOptions extends DecisionAnalyticsPeriodOptions {
  /** Maximum number of outcomes to return */
  limit?: number;
  /** Pagination offset */
  offset?: number;
}

/**
 * Interface for the internal client methods used by AnalyticsAPI.
 */
interface AnalyticsClientInterface {
  // Generic request method for extended endpoints
  request<T = unknown>(method: string, path: string, options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }): Promise<T>;

  // Core analytics methods
  getDisagreementAnalytics(params?: AnalyticsPeriodOptions): Promise<DisagreementAnalytics>;
  getRoleRotationAnalytics(params?: AnalyticsPeriodOptions): Promise<RoleRotationAnalytics>;
  getEarlyStopAnalytics(params?: AnalyticsPeriodOptions): Promise<EarlyStopAnalytics>;
  getConsensusQualityAnalytics(params?: AnalyticsPeriodOptions): Promise<ConsensusQualityAnalytics>;
  getRankingStats(): Promise<RankingStats>;
  getMemoryStats(): Promise<MemoryStats>;
}

/**
 * Analytics API namespace.
 *
 * Provides methods for retrieving analytics and metrics:
 * - Disagreement patterns between agents
 * - Role rotation statistics
 * - Early stop analysis
 * - Consensus quality metrics
 * - Ranking and memory statistics
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Get disagreement analytics for the last 7 days
 * const disagreements = await client.analytics.disagreements({ period: '7d' });
 *
 * // Get consensus quality metrics
 * const quality = await client.analytics.consensusQuality();
 *
 * // Get memory statistics
 * const memStats = await client.analytics.memoryStats();
 * ```
 */
export class AnalyticsAPI {
  constructor(private client: AnalyticsClientInterface) {}

  /**
   * Get disagreement analytics showing patterns of agent disagreements.
   */
  async disagreements(params?: AnalyticsPeriodOptions): Promise<DisagreementAnalytics> {
    return this.client.getDisagreementAnalytics(params);
  }

  /**
   * Get role rotation analytics showing how agents switch roles.
   */
  async roleRotation(params?: AnalyticsPeriodOptions): Promise<RoleRotationAnalytics> {
    return this.client.getRoleRotationAnalytics(params);
  }

  /**
   * Get early stop analytics showing debates that ended early.
   */
  async earlyStops(params?: AnalyticsPeriodOptions): Promise<EarlyStopAnalytics> {
    return this.client.getEarlyStopAnalytics(params);
  }

  /**
   * Get consensus quality analytics.
   */
  async consensusQuality(params?: AnalyticsPeriodOptions): Promise<ConsensusQualityAnalytics> {
    return this.client.getConsensusQualityAnalytics(params);
  }

  /**
   * Get ranking statistics for agents.
   */
  async rankingStats(): Promise<RankingStats> {
    return this.client.getRankingStats();
  }

  /**
   * Get memory system statistics.
   */
  async memoryStats(): Promise<MemoryStats> {
    return this.client.getMemoryStats();
  }

  // =========================================================================
  // Dashboard Overview
  // =========================================================================

  /**
   * Get dashboard summary with key metrics.
   */
  async getSummary(options?: { workspace_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/summary', { params: options });
  }

  /**
   * Get finding trends over time.
   */
  async getFindingTrends(options?: { workspace_id?: string; time_range?: string; granularity?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/trends/findings', { params: options });
  }

  /**
   * Get remediation performance metrics.
   */
  async getRemediationMetrics(options?: { workspace_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/remediation', { params: options });
  }

  /**
   * Get compliance scorecard.
   */
  async getComplianceScorecard(options?: { workspace_id?: string; frameworks?: string[] }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/compliance', { params: options });
  }

  /**
   * Get risk heatmap data.
   */
  async getRiskHeatmap(options?: { workspace_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/heatmap', { params: options });
  }

  // =========================================================================
  // Debate Analytics
  // =========================================================================

  /**
   * Get debates overview metrics.
   */
  async getDebatesOverview(): Promise<{ total: number; consensus_rate: number; average_rounds: number }> {
    return this.client.request('GET', '/api/analytics/debates/overview');
  }

  /**
   * Get debate trends over time.
   */
  async getDebateTrends(options?: { time_range?: string; granularity?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/debates/trends', { params: options });
  }

  /**
   * Get topic distribution and consensus by topic.
   */
  async getDebateTopics(options?: { time_range?: string; limit?: number }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/debates/topics', { params: options });
  }

  /**
   * Get debate outcome distribution.
   */
  async getDebateOutcomes(options?: { time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/debates/outcomes', { params: options });
  }

  /**
   * Get decision analytics overview metrics.
   */
  async getDecisionOverview(options?: DecisionAnalyticsPeriodOptions): Promise<unknown> {
    return this.client.request('GET', '/api/v1/decision-analytics/overview', {
      params: options,
    });
  }

  /**
   * Get decision quality trend data.
   */
  async getDecisionTrends(options?: DecisionAnalyticsPeriodOptions): Promise<unknown> {
    return this.client.request('GET', '/api/v1/decision-analytics/trends', {
      params: options,
    });
  }

  /**
   * Get paginated decision outcomes.
   */
  async getDecisionOutcomes(options?: DecisionAnalyticsOutcomesOptions): Promise<unknown> {
    return this.client.request('GET', '/api/v1/decision-analytics/outcomes', {
      params: options,
    });
  }

  /**
   * Get per-agent decision quality metrics.
   */
  async getDecisionAgents(options?: DecisionAnalyticsPeriodOptions): Promise<unknown> {
    return this.client.request('GET', '/api/v1/decision-analytics/agents', {
      params: options,
    });
  }

  /**
   * Get decision quality metrics grouped by domain.
   */
  async getDecisionDomains(options?: DecisionAnalyticsPeriodOptions): Promise<unknown> {
    return this.client.request('GET', '/api/v1/decision-analytics/domains', {
      params: options,
    });
  }

  /**
   * Get outcome analytics summary.
   */
  async getOutcomesSummary(options?: { period?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/outcomes', { params: options });
  }

  /**
   * Get outcome analytics average rounds.
   */
  async getOutcomesAverageRounds(options?: { period?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/outcomes/average-rounds', {
      params: options,
    });
  }

  /**
   * Get outcome analytics consensus rate.
   */
  async getOutcomesConsensusRate(options?: { period?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/outcomes/consensus-rate', {
      params: options,
    });
  }

  /**
   * Get outcome analytics contributions.
   */
  async getOutcomesContributions(options?: { period?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/outcomes/contributions', {
      params: options,
    });
  }

  /**
   * Get outcome analytics quality trend.
   */
  async getOutcomesQualityTrend(options?: { period?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/outcomes/quality-trend', {
      params: options,
    });
  }

  /**
   * Get outcome analytics topic distribution.
   */
  async getOutcomesTopics(options?: { period?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/outcomes/topics', { params: options });
  }

  /**
   * Get differentiation summary metrics.
   */
  async getDifferentiationSummary(): Promise<unknown> {
    return this.client.request('GET', '/api/differentiation/summary');
  }

  /**
   * Get differentiation vetting metrics.
   */
  async getDifferentiationVetting(): Promise<unknown> {
    return this.client.request('GET', '/api/differentiation/vetting');
  }

  /**
   * Get differentiation calibration metrics.
   */
  async getDifferentiationCalibration(): Promise<unknown> {
    return this.client.request('GET', '/api/differentiation/calibration');
  }

  /**
   * Get differentiation memory metrics.
   */
  async getDifferentiationMemory(): Promise<unknown> {
    return this.client.request('GET', '/api/differentiation/memory');
  }

  /**
   * Get differentiation benchmark metrics.
   */
  async getDifferentiationBenchmarks(): Promise<unknown> {
    return this.client.request('GET', '/api/differentiation/benchmarks');
  }
  // =========================================================================
  // Agent Analytics
  // =========================================================================

  /**
   * Get agent leaderboard with ELO rankings.
   */
  async getAgentLeaderboard(options?: { limit?: number; domain?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/agents/leaderboard', { params: options });
  }

  /**
   * Get individual agent performance statistics.
   */
  async getAgentPerformance(agentId: string, options?: { time_range?: string }): Promise<unknown> {
    return this.client.request('GET', `/api/analytics/agents/${agentId}/performance`, { params: options });
  }

  /**
   * Get multi-agent comparison.
   */
  async compareAgents(agents: string[]): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/agents/comparison', {
      params: { agents: agents.join(',') },
    });
  }

  /**
   * Get aggregate performance metrics for all agents.
   */
  async getAgentsPerformanceSummary(options?: {
    time_range?: string;
    org_id?: string;
    limit?: number;
  }): Promise<unknown> {
    return this.client.request('GET', '/api/v1/analytics/agents/performance', {
      params: options,
    });
  }

  /**
   * Get summary statistics for debates.
   */
  async getDebatesSummary(options?: {
    time_range?: string;
    org_id?: string;
  }): Promise<unknown> {
    return this.client.request('GET', '/api/v1/analytics/debates/summary', {
      params: options,
    });
  }

  /**
   * Get workspace-level usage metrics.
   */
  async getWorkspaceUsage(
    workspaceId: string,
    options?: { time_range?: string }
  ): Promise<unknown> {
    return this.client.request(
      'GET',
      `/api/v1/analytics/workspace/${workspaceId}/usage`,
      { params: options }
    );
  }

  /**
   * Get agent performance trends over time.
   */
  async getAgentTrends(options?: {
    agents?: string[];
    time_range?: string;
    granularity?: string;
  }): Promise<unknown> {
    const params: Record<string, unknown> = { ...options };
    if (options?.agents) params.agents = options.agents.join(',');
    return this.client.request('GET', '/api/analytics/agents/trends', { params });
  }

  /**
   * Get learning efficiency by agent and domain.
   */
  async getLearningEfficiency(options?: { agent?: string; domain?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/learning-efficiency', { params: options });
  }

  /**
   * Get voting accuracy metrics.
   */
  async getVotingAccuracy(options?: { agent?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/voting-accuracy', { params: options });
  }

  /**
   * Get calibration statistics.
   */
  async getCalibrationStats(options?: { agent?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/calibration', { params: options });
  }

  /**
   * Get cross-pollination metrics.
   */
  async getCrossPollination(): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/cross-pollination');
  }

  // =========================================================================
  // Usage & Costs
  // =========================================================================

  /**
   * Get token consumption trends.
   */
  async getTokenUsage(options?: { org_id?: string; time_range?: string; granularity?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/usage/tokens', { params: options });
  }

  /**
   * Get cost breakdown by provider and model.
   */
  async getCostBreakdown(options?: { org_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/usage/costs', { params: options });
  }

  /**
   * Get active user counts and growth.
   */
  async getActiveUsers(options?: { org_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/usage/active_users', { params: options });
  }

  /**
   * Get token usage summary by provider.
   */
  async getTokenSummary(options?: { org_id?: string; days?: number }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/tokens', { params: options });
  }

  /**
   * Get token usage trends.
   */
  async getTokenTrends(options?: { org_id?: string; days?: number; granularity?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/tokens/trends', { params: options });
  }

  /**
   * Get detailed breakdown by provider and model.
   */
  async getProviderBreakdown(options?: { org_id?: string; days?: number }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/tokens/providers', { params: options });
  }

  /**
   * Get cost analysis for audits.
   */
  async getCostMetrics(options?: { workspace_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/cost', { params: options });
  }

  /**
   * Get per-agent cost breakdown with budget utilization.
   * @route GET /api/analytics/cost/breakdown
   */
  async getCostBreakdownDashboard(options?: { workspace_id?: string; time_range?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/cost/breakdown', { params: options });
  }

  // =========================================================================
  // Flip Detection
  // =========================================================================

  /**
   * Get flip detection summary.
   */
  async getFlipSummary(): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/flips/summary');
  }

  /**
   * Get recent flip events.
   */
  async getRecentFlips(options?: { limit?: number; agent?: string; flip_type?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/flips/recent', { params: options });
  }

  /**
   * Get agent consistency scores.
   */
  async getAgentConsistency(agents?: string[]): Promise<unknown> {
    const params = agents ? { agents: agents.join(',') } : undefined;
    return this.client.request('GET', '/api/analytics/flips/consistency', { params });
  }

  /**
   * Get flip trends over time.
   */
  async getFlipTrends(options?: { days?: number; granularity?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/flips/trends', { params: options });
  }

  // =========================================================================
  // Deliberation Analytics
  // =========================================================================

  /**
   * Get deliberation summary.
   */
  async getDeliberationSummary(options?: { org_id?: string; days?: number }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/deliberations', { params: options });
  }

  /**
   * Get deliberations by channel.
   */
  async getDeliberationsByChannel(options?: { org_id?: string; days?: number }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/deliberations/channels', { params: options });
  }

  /**
   * Get consensus rates by agent team.
   */
  async getConsensusRates(options?: { org_id?: string; days?: number }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/deliberations/consensus', { params: options });
  }

  /**
   * Get deliberation performance metrics.
   */
  async getDeliberationPerformance(options?: { org_id?: string; days?: number; granularity?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/analytics/deliberations/performance', { params: options });
  }

  // =========================================================================
  // External Platforms
  // =========================================================================

  /**
   * List connected analytics platforms.
   */
  async listPlatforms(): Promise<{ platforms: unknown[] }> {
    return this.client.request('GET', '/api/v1/analytics/platforms');
  }

  /**
   * Connect a new analytics platform.
   */
  async connectPlatform(platform: string, credentials: Record<string, unknown>): Promise<{ connected: boolean }> {
    return this.client.request('POST', '/api/v1/analytics/connect', { json: { platform, credentials } });
  }

  /**
   * Disconnect an analytics platform.
   */
  async disconnectPlatform(platform: string): Promise<{ disconnected: boolean }> {
    return this.client.request('DELETE', `/api/v1/analytics/${platform}`);
  }

  /**
   * List dashboards from all platforms.
   */
  async listDashboards(): Promise<{ dashboards: unknown[] }> {
    return this.client.request('GET', '/api/v1/analytics/dashboards');
  }

  /**
   * List dashboards from a specific platform.
   */
  async listPlatformDashboards(platform: string): Promise<{ dashboards: unknown[] }> {
    return this.client.request('GET', `/api/v1/analytics/${platform}/dashboards`);
  }

  /**
   * Get a specific dashboard with cards.
   */
  async getDashboard(platform: string, dashboardId: string): Promise<unknown> {
    return this.client.request('GET', `/api/v1/analytics/${platform}/dashboards/${dashboardId}`);
  }

  /**
   * Execute unified query across platforms.
   */
  async executeQuery(query: string, options?: { platform?: string; params?: Record<string, unknown> }): Promise<unknown> {
    return this.client.request('POST', '/api/v1/analytics/query', { json: { query, ...options } });
  }

  /**
   * List available pre-built reports.
   */
  async listReports(): Promise<{ reports: unknown[] }> {
    return this.client.request('GET', '/api/v1/analytics/reports');
  }

  /**
   * Generate custom analytics report.
   */
  async generateReport(reportType: string, options?: Record<string, unknown>): Promise<unknown> {
    return this.client.request('POST', '/api/v1/analytics/reports/generate', { json: { type: reportType, ...options } });
  }

  /**
   * Get cross-platform metrics overview.
   */
  async getCrossplatformMetrics(): Promise<unknown> {
    return this.client.request('GET', '/api/v1/analytics/metrics');
  }

  /**
   * Get real-time metrics (GA4).
   */
  async getRealtimeMetrics(): Promise<unknown> {
    return this.client.request('GET', '/api/v1/analytics/realtime');
  }

  /**
   * Get event data from a platform.
   */
  async getPlatformEvents(platform: string, options?: { since?: string; limit?: number }): Promise<unknown> {
    return this.client.request('GET', `/api/v1/analytics/${platform}/events`, { params: options });
  }

  /**
   * Get funnel analysis (Mixpanel).
   */
  async getFunnels(platform: string, options?: { funnel_id?: string }): Promise<unknown> {
    return this.client.request('GET', `/api/v1/analytics/${platform}/funnels`, { params: options });
  }

  /**
   * Get retention analysis (Mixpanel).
   */
  async getRetention(platform: string, options?: { cohort?: string; period?: string }): Promise<unknown> {
    return this.client.request('GET', `/api/v1/analytics/${platform}/retention`, { params: options });
  }

  /**
   * Get analytics trends.
   */
  async getTrends(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/analytics/trends', { params }) as Promise<Record<string, unknown>>;
  }
}
