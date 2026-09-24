/**
 * Analytics API
 *
 * Handles analytics, metrics, and reporting operations.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface AnalyticsSummary {
  total_debates: number;
  total_messages: number;
  consensus_rate: number;
  avg_debate_duration_ms: number;
  active_users_24h: number;
  top_topics: Array<{ topic: string; count: number }>;
}

export interface AnalyticsOverview {
  total_debates: number;
  active_debates: number;
  completed_debates: number;
  failed_debates: number;
  avg_debate_duration_seconds: number;
  consensus_rate: number;
  period_days: number;
}

export interface FindingsTrend {
  date: string;
  findings_count: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface RemediationMetrics {
  total_findings: number;
  remediated: number;
  pending: number;
  avg_remediation_time_hours: number;
  remediation_rate: number;
}

export interface AgentMetrics {
  agent_id: string;
  name: string;
  debates_participated: number;
  avg_message_length: number;
  consensus_contribution: number;
  response_time_ms: number;
  elo_rating?: number;
}

export interface CostAnalysis {
  total_cost_usd: number;
  cost_by_model: Record<string, number>;
  cost_by_debate_type: Record<string, number>;
  projected_monthly_cost: number;
  cost_trend: Array<{ date: string; cost: number }>;
}

export interface ComplianceScore {
  overall_score: number;
  categories: Array<{ category: string; score: number; max_score: number; findings: number }>;
  last_audit: string;
}

export interface HeatmapData {
  x_labels: string[];
  y_labels: string[];
  values: number[][];
  max_value: number;
}

export interface DisagreementStats {
  total_disagreements: number;
  avg_disagreement_intensity: number;
  resolved_rate: number;
  top_disagreement_topics: Array<{ topic: string; count: number }>;
}

// =============================================================================
// Analytics API Class
// =============================================================================

export class AnalyticsAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  /**
   * Get analytics overview
   */
  async overview(days = 30): Promise<unknown> {
    return this.http.get(`/api/analytics?days=${days}`);
  }

  /**
   * Get dashboard summary metrics
   */
  async summary(): Promise<{ summary: AnalyticsSummary }> {
    return this.http.get('/api/analytics/summary');
  }

  /**
   * Get finding trends over time
   */
  async findingsTrends(days = 30): Promise<{ trends: FindingsTrend[] }> {
    return this.http.get(`/api/analytics/trends/findings?days=${days}`);
  }

  /**
   * Get remediation metrics
   */
  async remediation(): Promise<{ metrics: RemediationMetrics }> {
    return this.http.get('/api/analytics/remediation');
  }

  /**
   * Get agent performance metrics
   */
  async agents(): Promise<{ agents: AgentMetrics[] }> {
    return this.http.get('/api/analytics/agents');
  }

  /**
   * Get cost analysis
   */
  async cost(days = 30): Promise<{ analysis: CostAnalysis }> {
    return this.http.get(`/api/analytics/cost?days=${days}`);
  }

  /**
   * Get compliance scorecard
   */
  async compliance(): Promise<{ compliance: ComplianceScore }> {
    return this.http.get('/api/analytics/compliance');
  }

  /**
   * Get risk heatmap data
   */
  async heatmap(): Promise<{ heatmap: HeatmapData }> {
    return this.http.get('/api/analytics/heatmap');
  }

  /**
   * Get disagreement statistics
   */
  async disagreements(): Promise<{ stats: DisagreementStats }> {
    return this.http.get('/api/analytics/disagreements');
  }

  /**
   * Get role rotation statistics
   */
  async roleRotation(): Promise<{ stats: unknown }> {
    return this.http.get('/api/analytics/role-rotation');
  }

  /**
   * Get early stopping statistics
   */
  async earlyStops(): Promise<{ stats: unknown }> {
    return this.http.get('/api/analytics/early-stops');
  }

  /**
   * Get consensus quality metrics
   */
  async consensusQuality(): Promise<{ stats: unknown }> {
    return this.http.get('/api/analytics/consensus-quality');
  }
}
