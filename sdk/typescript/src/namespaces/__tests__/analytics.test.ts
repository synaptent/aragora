/**
 * Analytics Namespace Tests
 *
 * Comprehensive tests for the AnalyticsAPI namespace class.
 * Tests all methods including:
 * - Core analytics (disagreements, role rotation, early stops)
 * - Consensus quality
 * - Ranking and memory stats
 * - Dashboard overview
 * - Debate analytics
 * - Agent analytics
 * - Usage and costs
 * - Flip detection
 * - Deliberation analytics
 * - External platforms
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { AnalyticsAPI } from '../analytics';

interface MockClient {
  request: Mock;
  getDisagreementAnalytics: Mock;
  getRoleRotationAnalytics: Mock;
  getEarlyStopAnalytics: Mock;
  getConsensusQualityAnalytics: Mock;
  getRankingStats: Mock;
  getMemoryStats: Mock;
}

function createMockClient(): MockClient {
  return {
    request: vi.fn(),
    getDisagreementAnalytics: vi.fn(),
    getRoleRotationAnalytics: vi.fn(),
    getEarlyStopAnalytics: vi.fn(),
    getConsensusQualityAnalytics: vi.fn(),
    getRankingStats: vi.fn(),
    getMemoryStats: vi.fn(),
  };
}

describe('AnalyticsAPI', () => {
  let api: AnalyticsAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = createMockClient();
    api = new AnalyticsAPI(mockClient as any);
  });

  // ===========================================================================
  // Core Analytics Methods
  // ===========================================================================

  describe('Core Analytics Methods', () => {
    it('should get disagreement analytics', async () => {
      const mockData = {
        total_disagreements: 150,
        patterns: [{ agents: ['claude', 'gpt4'], frequency: 25 }],
      };
      mockClient.getDisagreementAnalytics.mockResolvedValue(mockData);

      const result = await api.disagreements({ period: '7d' });

      expect(mockClient.getDisagreementAnalytics).toHaveBeenCalledWith({ period: '7d' });
      expect(result.total_disagreements).toBe(150);
    });

    it('should get disagreement analytics without params', async () => {
      const mockData = { total_disagreements: 100 };
      mockClient.getDisagreementAnalytics.mockResolvedValue(mockData);

      const result = await api.disagreements();

      expect(mockClient.getDisagreementAnalytics).toHaveBeenCalledWith(undefined);
      expect(result.total_disagreements).toBe(100);
    });

    it('should get role rotation analytics', async () => {
      const mockData = {
        total_rotations: 200,
        by_agent: { claude: 50, gpt4: 45 },
      };
      mockClient.getRoleRotationAnalytics.mockResolvedValue(mockData);

      const result = await api.roleRotation({ period: '30d' });

      expect(mockClient.getRoleRotationAnalytics).toHaveBeenCalledWith({ period: '30d' });
      expect(result.total_rotations).toBe(200);
    });

    it('should get early stop analytics', async () => {
      const mockData = {
        total_early_stops: 30,
        rate: 0.06,
      };
      mockClient.getEarlyStopAnalytics.mockResolvedValue(mockData);

      const result = await api.earlyStops({ period: '7d' });

      expect(mockClient.getEarlyStopAnalytics).toHaveBeenCalledWith({ period: '7d' });
      expect(result.total_early_stops).toBe(30);
    });

    it('should get consensus quality analytics', async () => {
      const mockData = {
        average_quality: 0.85,
        by_domain: { technology: 0.88, business: 0.82 },
      };
      mockClient.getConsensusQualityAnalytics.mockResolvedValue(mockData);

      const result = await api.consensusQuality({ period: '90d' });

      expect(mockClient.getConsensusQualityAnalytics).toHaveBeenCalledWith({ period: '90d' });
      expect(result.average_quality).toBe(0.85);
    });

    it('should get ranking stats', async () => {
      const mockData = {
        total_agents: 15,
        average_elo: 1450,
      };
      mockClient.getRankingStats.mockResolvedValue(mockData);

      const result = await api.rankingStats();

      expect(mockClient.getRankingStats).toHaveBeenCalledTimes(1);
      expect(result.total_agents).toBe(15);
    });

    it('should get memory stats', async () => {
      const mockData = {
        total_memories: 5000,
        by_tier: { fast: 1000, medium: 2000, slow: 1500, glacial: 500 },
      };
      mockClient.getMemoryStats.mockResolvedValue(mockData);

      const result = await api.memoryStats();

      expect(mockClient.getMemoryStats).toHaveBeenCalledTimes(1);
      expect(result.total_memories).toBe(5000);
    });
  });

  // ===========================================================================
  // Dashboard Overview
  // ===========================================================================

  describe('Dashboard Overview', () => {
    it('should get dashboard summary', async () => {
      const mockSummary = {
        total_debates: 1500,
        active_debates: 25,
        consensus_rate: 0.85,
      };
      mockClient.request.mockResolvedValue(mockSummary);

      const result = await api.getSummary();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/summary', { params: undefined });
      expect(result).toHaveProperty('total_debates');
    });

    it('should get dashboard summary with workspace filter', async () => {
      const mockSummary = { total_debates: 50 };
      mockClient.request.mockResolvedValue(mockSummary);

      await api.getSummary({ workspace_id: 'ws_123', time_range: '7d' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/summary', {
        params: { workspace_id: 'ws_123', time_range: '7d' },
      });
    });

    it('should get finding trends', async () => {
      const mockTrends = {
        data: [{ date: '2024-01-20', count: 15 }],
      };
      mockClient.request.mockResolvedValue(mockTrends);

      const result = await api.getFindingTrends({ time_range: '30d', granularity: 'day' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/trends/findings', {
        params: { time_range: '30d', granularity: 'day' },
      });
      expect(result.data).toHaveLength(1);
    });

    it('should get remediation metrics', async () => {
      const mockMetrics = { average_time_to_fix: 3600 };
      mockClient.request.mockResolvedValue(mockMetrics);

      const result = await api.getRemediationMetrics();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/remediation', {
        params: undefined,
      });
      expect(result).toHaveProperty('average_time_to_fix');
    });

    it('should get compliance scorecard', async () => {
      const mockScorecard = { overall_score: 0.92 };
      mockClient.request.mockResolvedValue(mockScorecard);

      const result = await api.getComplianceScorecard({ frameworks: ['SOC2'] });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/compliance', {
        params: { frameworks: ['SOC2'] },
      });
      expect(result.overall_score).toBe(0.92);
    });

    it('should get risk heatmap', async () => {
      const mockHeatmap = { cells: [] };
      mockClient.request.mockResolvedValue(mockHeatmap);

      const result = await api.getRiskHeatmap({ time_range: '90d' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/heatmap', {
        params: { time_range: '90d' },
      });
      expect(result).toHaveProperty('cells');
    });
  });

  // ===========================================================================
  // Debate Analytics
  // ===========================================================================

  describe('Debate Analytics', () => {
    it('should get debates overview', async () => {
      const mockOverview = {
        total: 500,
        consensus_rate: 0.78,
        average_rounds: 3.5,
      };
      mockClient.request.mockResolvedValue(mockOverview);

      const result = await api.getDebatesOverview();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/debates/overview');
      expect(result.total).toBe(500);
      expect(result.consensus_rate).toBe(0.78);
    });

    it('should get debate trends', async () => {
      const mockTrends = {
        data: [{ date: '2024-01-20', debates: 15 }],
      };
      mockClient.request.mockResolvedValue(mockTrends);

      const result = await api.getDebateTrends({ time_range: '30d', granularity: 'week' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/debates/trends', {
        params: { time_range: '30d', granularity: 'week' },
      });
      expect(result.data).toHaveLength(1);
    });

    it('should get debate topics', async () => {
      const mockTopics = {
        topics: [{ topic: 'AI Ethics', count: 50 }],
      };
      mockClient.request.mockResolvedValue(mockTopics);

      const result = await api.getDebateTopics({ limit: 10 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/debates/topics', {
        params: { limit: 10 },
      });
      expect(result.topics).toHaveLength(1);
    });

    it('should get debate outcomes', async () => {
      const mockOutcomes = {
        consensus: 400,
        majority: 80,
        no_consensus: 20,
      };
      mockClient.request.mockResolvedValue(mockOutcomes);

      const result = await api.getDebateOutcomes();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/debates/outcomes', {
        params: undefined,
      });
      expect(result.consensus).toBe(400);
    });
  });

  describe('Decision Analytics', () => {
    it('should get decision analytics endpoints', async () => {
      mockClient.request.mockResolvedValue({ data: {} });

      await api.getDecisionOverview({ period: '7d' });
      await api.getDecisionTrends({ period: '90d' });
      await api.getDecisionOutcomes({ period: '30d', limit: 25, offset: 50 });
      await api.getDecisionAgents({ period: '30d' });
      await api.getDecisionDomains({ period: '30d' });

      expect(mockClient.request).toHaveBeenNthCalledWith(
        1,
        'GET',
        '/api/v1/decision-analytics/overview',
        { params: { period: '7d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        2,
        'GET',
        '/api/v1/decision-analytics/trends',
        { params: { period: '90d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        3,
        'GET',
        '/api/v1/decision-analytics/outcomes',
        { params: { period: '30d', limit: 25, offset: 50 } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        4,
        'GET',
        '/api/v1/decision-analytics/agents',
        { params: { period: '30d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        5,
        'GET',
        '/api/v1/decision-analytics/domains',
        { params: { period: '30d' } }
      );
    });
  });

  // ===========================================================================
  // Outcome Analytics
  // ===========================================================================

  describe('Outcome Analytics', () => {
    it('should get outcome analytics endpoints', async () => {
      mockClient.request.mockResolvedValue({ data: {} });

      await api.getOutcomesSummary({ period: '7d' });
      await api.getOutcomesAverageRounds({ period: '7d' });
      await api.getOutcomesConsensusRate({ period: '7d' });
      await api.getOutcomesContributions({ period: '7d' });
      await api.getOutcomesQualityTrend({ period: '7d' });
      await api.getOutcomesTopics({ period: '7d' });

      expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/analytics/outcomes', {
        params: { period: '7d' },
      });
      expect(mockClient.request).toHaveBeenNthCalledWith(
        2,
        'GET',
        '/api/analytics/outcomes/average-rounds',
        { params: { period: '7d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        3,
        'GET',
        '/api/analytics/outcomes/consensus-rate',
        { params: { period: '7d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        4,
        'GET',
        '/api/analytics/outcomes/contributions',
        { params: { period: '7d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        5,
        'GET',
        '/api/analytics/outcomes/quality-trend',
        { params: { period: '7d' } }
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        6,
        'GET',
        '/api/analytics/outcomes/topics',
        { params: { period: '7d' } }
      );
    });
  });

  describe('Differentiation Analytics', () => {
    it('should get differentiation endpoints', async () => {
      mockClient.request.mockResolvedValue({ data: {} });

      await api.getDifferentiationSummary();
      await api.getDifferentiationVetting();
      await api.getDifferentiationCalibration();
      await api.getDifferentiationMemory();
      await api.getDifferentiationBenchmarks();

      expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/differentiation/summary');
      expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/differentiation/vetting');
      expect(mockClient.request).toHaveBeenNthCalledWith(
        3,
        'GET',
        '/api/differentiation/calibration'
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(4, 'GET', '/api/differentiation/memory');
      expect(mockClient.request).toHaveBeenNthCalledWith(
        5,
        'GET',
        '/api/differentiation/benchmarks'
      );
    });
  });
  // ===========================================================================
  // Agent Analytics
  // ===========================================================================

  describe('Agent Analytics', () => {
    it('should get agent leaderboard', async () => {
      const mockLeaderboard = {
        agents: [
          { name: 'claude', elo: 1850 },
          { name: 'gpt4', elo: 1800 },
        ],
      };
      mockClient.request.mockResolvedValue(mockLeaderboard);

      const result = await api.getAgentLeaderboard({ limit: 10, domain: 'technology' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/agents/leaderboard', {
        params: { limit: 10, domain: 'technology' },
      });
      expect(result.agents).toHaveLength(2);
    });

    it('should get agent performance', async () => {
      const mockPerf = {
        agent: 'claude',
        win_rate: 0.75,
        elo: 1850,
      };
      mockClient.request.mockResolvedValue(mockPerf);

      const result = await api.getAgentPerformance('claude', { time_range: '30d' });

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/analytics/agents/claude/performance',
        { params: { time_range: '30d' } }
      );
      expect(result.win_rate).toBe(0.75);
    });

    it('should compare agents', async () => {
      const mockComparison = {
        agents: ['claude', 'gpt4'],
        metrics: { win_rate: { claude: 0.75, gpt4: 0.72 } },
      };
      mockClient.request.mockResolvedValue(mockComparison);

      const result = await api.compareAgents(['claude', 'gpt4']);

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/agents/comparison', {
        params: { agents: 'claude,gpt4' },
      });
      expect(result.agents).toHaveLength(2);
    });

    it('should get learning efficiency', async () => {
      const mockEfficiency = { agent: 'claude', efficiency: 0.92 };
      mockClient.request.mockResolvedValue(mockEfficiency);

      const result = await api.getLearningEfficiency({ agent: 'claude', domain: 'technology' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/learning-efficiency', {
        params: { agent: 'claude', domain: 'technology' },
      });
      expect(result.efficiency).toBe(0.92);
    });
  });

  // ===========================================================================
  // Usage & Costs
  // ===========================================================================

  describe('Usage & Costs', () => {
    it('should get token usage', async () => {
      const mockUsage = { total_tokens: 2500000 };
      mockClient.request.mockResolvedValue(mockUsage);

      const result = await api.getTokenUsage({ time_range: '30d' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/usage/tokens', {
        params: { time_range: '30d' },
      });
      expect(result.total_tokens).toBe(2500000);
    });

    it('should get cost breakdown', async () => {
      const mockCosts = {
        total_cost: 150.00,
        by_provider: { anthropic: 80, openai: 50, mistral: 20 },
      };
      mockClient.request.mockResolvedValue(mockCosts);

      const result = await api.getCostBreakdown();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/usage/costs', {
        params: undefined,
      });
      expect(result.total_cost).toBe(150.00);
    });

    it('should get active users', async () => {
      const mockUsers = { active_users: 42 };
      mockClient.request.mockResolvedValue(mockUsers);

      const result = await api.getActiveUsers({ time_range: '7d' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/usage/active_users', {
        params: { time_range: '7d' },
      });
      expect(result.active_users).toBe(42);
    });

    it('should get cost metrics', async () => {
      const mockMetrics = { total_cost: 500 };
      mockClient.request.mockResolvedValue(mockMetrics);

      const result = await api.getCostMetrics({ workspace_id: 'ws_1' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/cost', {
        params: { workspace_id: 'ws_1' },
      });
      expect(result.total_cost).toBe(500);
    });
  });

  // ===========================================================================
  // Flip Detection
  // ===========================================================================

  describe('Flip Detection', () => {
    it('should get flip summary', async () => {
      const mockSummary = { total_flips: 25, by_agent: { claude: 5 } };
      mockClient.request.mockResolvedValue(mockSummary);

      const result = await api.getFlipSummary();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/flips/summary');
      expect(result.total_flips).toBe(25);
    });

    it('should get recent flips', async () => {
      const mockFlips = {
        flips: [{ agent: 'claude', topic: 'Topic 1' }],
      };
      mockClient.request.mockResolvedValue(mockFlips);

      const result = await api.getRecentFlips({ limit: 10, agent: 'claude' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/flips/recent', {
        params: { limit: 10, agent: 'claude' },
      });
      expect(result.flips).toHaveLength(1);
    });

    it('should get agent consistency scores', async () => {
      const mockConsistency = { claude: 0.92, gpt4: 0.88 };
      mockClient.request.mockResolvedValue(mockConsistency);

      const result = await api.getAgentConsistency(['claude', 'gpt4']);

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/flips/consistency', {
        params: { agents: 'claude,gpt4' },
      });
      expect(result).toHaveProperty('claude');
    });

    it('should get flip trends', async () => {
      const mockTrends = { data: [{ date: '2024-01-20', flips: 3 }] };
      mockClient.request.mockResolvedValue(mockTrends);

      const result = await api.getFlipTrends({ days: 30 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/analytics/flips/trends', {
        params: { days: 30 },
      });
      expect(result.data).toHaveLength(1);
    });
  });

  // ===========================================================================
  // External Platforms
  // ===========================================================================

  describe('External Platforms', () => {
    it('should list platforms', async () => {
      const mockPlatforms = { platforms: [{ name: 'google_analytics' }] };
      mockClient.request.mockResolvedValue(mockPlatforms);

      const result = await api.listPlatforms();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/analytics/platforms');
      expect(result.platforms).toHaveLength(1);
    });

    it('should connect a platform', async () => {
      mockClient.request.mockResolvedValue({ connected: true });

      const result = await api.connectPlatform('mixpanel', { api_key: 'key123' });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/analytics/connect', {
        json: { platform: 'mixpanel', credentials: { api_key: 'key123' } },
      });
      expect(result.connected).toBe(true);
    });

    it('should disconnect a platform', async () => {
      mockClient.request.mockResolvedValue({ disconnected: true });

      const result = await api.disconnectPlatform('mixpanel');

      expect(mockClient.request).toHaveBeenCalledWith('DELETE', '/api/v1/analytics/mixpanel');
      expect(result.disconnected).toBe(true);
    });

    it('should list dashboards', async () => {
      const mockDashboards = { dashboards: [{ id: 'd1', name: 'Overview' }] };
      mockClient.request.mockResolvedValue(mockDashboards);

      const result = await api.listDashboards();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/analytics/dashboards');
      expect(result.dashboards).toHaveLength(1);
    });

    it('should execute a query', async () => {
      const mockResult = { rows: [{ metric: 'pageviews', value: 1000 }] };
      mockClient.request.mockResolvedValue(mockResult);

      const result = await api.executeQuery('SELECT * FROM events', { platform: 'mixpanel' });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/analytics/query', {
        json: { query: 'SELECT * FROM events', platform: 'mixpanel' },
      });
      expect(result.rows).toHaveLength(1);
    });

    it('should generate a report', async () => {
      const mockReport = { report_id: 'rpt_1', status: 'generating' };
      mockClient.request.mockResolvedValue(mockReport);

      const result = await api.generateReport('monthly_summary', { format: 'pdf' });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/analytics/reports/generate', {
        json: { type: 'monthly_summary', format: 'pdf' },
      });
      expect(result.report_id).toBe('rpt_1');
    });

    it('should get real-time metrics', async () => {
      const mockRealtime = { active_users: 42, events_per_minute: 120 };
      mockClient.request.mockResolvedValue(mockRealtime);

      const result = await api.getRealtimeMetrics();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/analytics/realtime');
      expect(result.active_users).toBe(42);
    });
  });
});
