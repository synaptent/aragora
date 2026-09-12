/**
 * Agents Namespace Tests
 *
 * Comprehensive tests for the AgentsAPI namespace class.
 * Tests all methods including:
 * - Core listing and retrieval operations
 * - Agent profiles and performance metrics
 * - Calibration and ELO ratings
 * - Head-to-head matchups and comparisons
 * - Team selection
 * - Agent relationships (allies, rivals)
 * - Registration and lifecycle management
 * - Quota management
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AgentsAPI } from '../agents';
import type { AgentsClientInterface } from '../agents';

// Helper to create a mock client
function createMockClient(): AgentsClientInterface {
  return {
    listAgents: vi.fn(),
    listAgentsAvailability: vi.fn(),
    listAgentsHealth: vi.fn(),
    listLocalAgents: vi.fn(),
    getLocalAgentsStatus: vi.fn(),
    getAgent: vi.fn(),
    getAgentProfile: vi.fn(),
    getAgentHistory: vi.fn(),
    getAgentCalibration: vi.fn(),
    getAgentCalibrationCurve: vi.fn(),
    getAgentCalibrationSummary: vi.fn(),
    getAgentPerformance: vi.fn(),
    getAgentHeadToHead: vi.fn(),
    getAgentOpponentBriefing: vi.fn(),
    getAgentConsistency: vi.fn(),
    getAgentFlips: vi.fn(),
    getAgentPositions: vi.fn(),
    getAgentNetwork: vi.fn(),
    getAgentAllies: vi.fn(),
    getAgentRivals: vi.fn(),
    getAgentRelationship: vi.fn(),
    getAgentReputation: vi.fn(),
    getAgentMoments: vi.fn(),
    getAgentDomains: vi.fn(),
    getAgentElo: vi.fn(),
    getLeaderboard: vi.fn(),
    compareAgents: vi.fn(),
    getAgentMetadata: vi.fn(),
    getAgentIntrospection: vi.fn(),
    getLeaderboardView: vi.fn(),
    getRecentMatches: vi.fn(),
    getRecentFlips: vi.fn(),
    getFlipsSummary: vi.fn(),
    getCalibrationLeaderboard: vi.fn(),
    selectTeam: vi.fn(),
    request: vi.fn(),
  };
}

describe('AgentsAPI', () => {
  let mockClient: ReturnType<typeof createMockClient>;
  let agentsApi: AgentsAPI;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = createMockClient();
    agentsApi = new AgentsAPI(mockClient as any);
  });

  // ===========================================================================
  // Core Listing and Retrieval
  // ===========================================================================

  describe('Core Listing and Retrieval', () => {
    it('should list all agents', async () => {
      const mockAgents = {
        agents: [
          { name: 'claude', elo: 1520, matches: 100 },
          { name: 'gpt-4', elo: 1480, matches: 95 },
        ],
      };
      mockClient.listAgents.mockResolvedValueOnce(mockAgents);

      const result = await agentsApi.list();

      expect(mockClient.listAgents).toHaveBeenCalledTimes(1);
      expect(result.agents).toHaveLength(2);
      expect(result.agents[0].name).toBe('claude');
    });

    it('should get agent availability', async () => {
      const mockAvailability = {
        available: ['claude', 'gpt-4'],
        missing: ['llama'],
      };
      mockClient.listAgentsAvailability.mockResolvedValueOnce(mockAvailability);

      const result = await agentsApi.getAvailability();

      expect(mockClient.listAgentsAvailability).toHaveBeenCalledTimes(1);
      expect(result.available).toContain('claude');
      expect(result.missing).toContain('llama');
    });

    it('should get agent health status', async () => {
      const mockHealth = {
        claude: { status: 'healthy', latency_ms: 120 },
        'gpt-4': { status: 'degraded', latency_ms: 500 },
      };
      mockClient.listAgentsHealth.mockResolvedValueOnce(mockHealth);

      const result = await agentsApi.getHealth();

      expect(mockClient.listAgentsHealth).toHaveBeenCalledTimes(1);
      expect(result).toHaveProperty('claude');
    });

    it('should list local agents', async () => {
      const mockLocal = { agents: ['local-agent-1'], count: 1 };
      mockClient.listLocalAgents.mockResolvedValueOnce(mockLocal);

      const result = await agentsApi.listLocal();

      expect(mockClient.listLocalAgents).toHaveBeenCalledTimes(1);
      expect(result).toHaveProperty('agents');
    });

    it('should get local agent status', async () => {
      const mockStatus = { running: true, agents: 2 };
      mockClient.getLocalAgentsStatus.mockResolvedValueOnce(mockStatus);

      const result = await agentsApi.getLocalStatus();

      expect(mockClient.getLocalAgentsStatus).toHaveBeenCalledTimes(1);
      expect(result).toHaveProperty('running');
    });

    it('should get a specific agent by name', async () => {
      const mockAgent = { name: 'claude', elo: 1520, matches: 100 };
      mockClient.getAgent.mockResolvedValueOnce(mockAgent);

      const result = await agentsApi.get('claude');

      expect(mockClient.getAgent).toHaveBeenCalledWith('claude');
      expect(result.name).toBe('claude');
    });
  });

  // ===========================================================================
  // Agent Profiles and Details
  // ===========================================================================

  describe('Agent Profiles and Details', () => {
    it('should get agent profile', async () => {
      const mockProfile = {
        name: 'claude',
        elo: 1520,
        reputation: 0.92,
        consistency_score: 0.88,
      };
      mockClient.getAgentProfile.mockResolvedValueOnce(mockProfile);

      const result = await agentsApi.getProfile('claude');

      expect(mockClient.getAgentProfile).toHaveBeenCalledWith('claude');
      expect(result.reputation).toBe(0.92);
    });

    it('should get agent history with pagination', async () => {
      const mockHistory = {
        matches: [
          { debate_id: 'd1', result: 'win' },
          { debate_id: 'd2', result: 'loss' },
        ],
      };
      mockClient.getAgentHistory.mockResolvedValueOnce(mockHistory);

      const result = await agentsApi.getHistory('claude', { limit: 10, offset: 0 });

      expect(mockClient.getAgentHistory).toHaveBeenCalledWith('claude', { limit: 10, offset: 0 });
      expect(result.matches).toHaveLength(2);
    });

    it('should get agent persona', async () => {
      const mockPersona = {
        agent_name: 'claude',
        description: 'An AI assistant',
        traits: ['analytical', 'thorough'],
      };
      mockClient.request.mockResolvedValueOnce(mockPersona);

      const result = await agentsApi.getPersona('claude');

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/agent/claude/persona'
      );
      expect(result.agent_name).toBe('claude');
      expect(result.traits).toContain('analytical');
    });

    it('should delete agent persona', async () => {
      const mockResult = { success: true, message: 'Persona deleted' };
      mockClient.request.mockResolvedValueOnce(mockResult);

      const result = await agentsApi.deletePersona('claude');

      expect(mockClient.request).toHaveBeenCalledWith(
        'DELETE',
        '/api/agent/claude/persona'
      );
      expect(result.success).toBe(true);
    });

    it('should get grounded persona', async () => {
      const mockGrounded = {
        agent_name: 'claude',
        elo: 1520,
        domain_elos: { software: 1550 },
        win_rate: 0.6,
        calibration_score: 0.92,
        position_accuracy: 0.85,
        debates_count: 100,
      };
      mockClient.request.mockResolvedValueOnce(mockGrounded);

      const result = await agentsApi.getGroundedPersona('claude');

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/agent/claude/grounded-persona'
      );
      expect(result.elo).toBe(1520);
    });

    it('should get identity prompt', async () => {
      const mockIdentity = {
        agent_name: 'claude',
        prompt: 'You are Claude...',
        token_count: 250,
      };
      mockClient.request.mockResolvedValueOnce(mockIdentity);

      const result = await agentsApi.getIdentityPrompt('claude');

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/agent/claude/identity-prompt'
      );
      expect(result.prompt).toContain('Claude');
    });

    it('should get agent metadata', async () => {
      const mockMetadata = {
        model: 'claude-3-opus',
        provider: 'anthropic',
        version: '2024-01',
      };
      mockClient.getAgentMetadata.mockResolvedValueOnce(mockMetadata);

      const result = await agentsApi.getMetadata('claude');

      expect(mockClient.getAgentMetadata).toHaveBeenCalledWith('claude');
      expect(result).toHaveProperty('model');
    });

    it('should get agent introspection', async () => {
      const mockIntrospection = {
        self_awareness: 0.85,
        meta_reasoning: 0.88,
      };
      mockClient.getAgentIntrospection.mockResolvedValueOnce(mockIntrospection);

      const result = await agentsApi.getIntrospection('claude');

      expect(mockClient.getAgentIntrospection).toHaveBeenCalledWith('claude');
      expect(result).toHaveProperty('self_awareness');
    });
  });

  // ===========================================================================
  // Performance and Calibration
  // ===========================================================================

  describe('Performance and Calibration', () => {
    it('should get agent performance', async () => {
      const mockPerf = {
        agent: 'claude',
        elo: 1520,
        win_rate: 0.6,
        avg_confidence: 0.85,
      };
      mockClient.getAgentPerformance.mockResolvedValueOnce(mockPerf);

      const result = await agentsApi.getPerformance('claude');

      expect(mockClient.getAgentPerformance).toHaveBeenCalledWith('claude');
      expect(result.win_rate).toBe(0.6);
    });

    it('should get agent calibration', async () => {
      const mockCalib = {
        agent: 'claude',
        score: 0.92,
        brier_score: 0.08,
      };
      mockClient.getAgentCalibration.mockResolvedValueOnce(mockCalib);

      const result = await agentsApi.getCalibration('claude');

      expect(mockClient.getAgentCalibration).toHaveBeenCalledWith('claude');
      expect(result.score).toBe(0.92);
    });

    it('should get calibration curve', async () => {
      const mockCurve = {
        buckets: [{ predicted: 0.1, actual: 0.08 }],
      };
      mockClient.getAgentCalibrationCurve.mockResolvedValueOnce(mockCurve);

      const result = await agentsApi.getCalibrationCurve('claude');

      expect(mockClient.getAgentCalibrationCurve).toHaveBeenCalledWith('claude');
      expect(result).toHaveProperty('buckets');
    });

    it('should get calibration summary', async () => {
      const mockSummary = { overall_score: 0.9 };
      mockClient.getAgentCalibrationSummary.mockResolvedValueOnce(mockSummary);

      const result = await agentsApi.getCalibrationSummary('claude');

      expect(mockClient.getAgentCalibrationSummary).toHaveBeenCalledWith('claude');
      expect(result).toHaveProperty('overall_score');
    });

    it('should get agent consistency', async () => {
      const mockConsist = {
        agent: 'claude',
        overall_score: 0.88,
        position_stability: 0.85,
      };
      mockClient.getAgentConsistency.mockResolvedValueOnce(mockConsist);

      const result = await agentsApi.getConsistency('claude');

      expect(mockClient.getAgentConsistency).toHaveBeenCalledWith('claude');
      expect(result.overall_score).toBe(0.88);
    });

    it('should get agent accuracy', async () => {
      const mockAccuracy = {
        agent_name: 'claude',
        accuracy_rate: 0.85,
        total_positions: 500,
      };
      mockClient.request.mockResolvedValueOnce(mockAccuracy);

      const result = await agentsApi.getAccuracy('claude');

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/agent/claude/accuracy'
      );
      expect(result.accuracy_rate).toBe(0.85);
    });
  });

  // ===========================================================================
  // ELO and Rankings
  // ===========================================================================

  describe('ELO and Rankings', () => {
    it('should get agent ELO', async () => {
      const mockElo = {
        agent: 'claude',
        elo: 1520,
        history: [{ date: '2024-01-01', elo: 1500 }],
      };
      mockClient.getAgentElo.mockResolvedValueOnce(mockElo);

      const result = await agentsApi.getElo('claude');

      expect(mockClient.getAgentElo).toHaveBeenCalledWith('claude');
      expect(result.elo).toBe(1520);
    });

    it('should get leaderboard', async () => {
      const mockLeaderboard = {
        agents: [
          { name: 'claude', elo: 1520 },
          { name: 'gpt-4', elo: 1480 },
        ],
      };
      mockClient.getLeaderboard.mockResolvedValueOnce(mockLeaderboard);

      const result = await agentsApi.getLeaderboard();

      expect(mockClient.getLeaderboard).toHaveBeenCalledTimes(1);
      expect(result.agents).toHaveLength(2);
    });

    it('should get rankings with filters', async () => {
      const mockRankings = {
        rankings: [{ agent: 'claude', elo: 1520, rank: 1 }],
      };
      mockClient.request.mockResolvedValueOnce(mockRankings);

      const result = await agentsApi.getRankings({
        domain: 'software',
        limit: 10,
        sortBy: 'elo',
      });

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/v1/rankings',
        expect.objectContaining({
          params: expect.objectContaining({
            domain: 'software',
            limit: 10,
            sort_by: 'elo',
          }),
        })
      );
    });

    it('should update agent ELO', async () => {
      const mockUpdate = {
        agent: 'claude',
        elo: 1530,
        previous_elo: 1520,
        change: 10,
      };
      mockClient.request.mockResolvedValueOnce(mockUpdate);

      const result = await agentsApi.updateElo('claude', 10, {
        debateId: 'debate-123',
        reason: 'Won debate',
      });

      expect(mockClient.request).toHaveBeenCalledWith(
        'POST',
        '/api/v1/agents/claude/elo',
        {
          body: {
            elo_change: 10,
            debate_id: 'debate-123',
            reason: 'Won debate',
          },
        }
      );
      expect(result.elo).toBe(1530);
    });

    it('should get calibration leaderboard', async () => {
      const mockCalibLeaderboard = {
        agents: [{ name: 'claude', score: 0.95 }],
      };
      mockClient.getCalibrationLeaderboard.mockResolvedValueOnce(mockCalibLeaderboard);

      const result = await agentsApi.getCalibrationLeaderboard();

      expect(mockClient.getCalibrationLeaderboard).toHaveBeenCalledTimes(1);
      expect(result.agents[0].score).toBe(0.95);
    });

    it('should get leaderboard view', async () => {
      const mockView = {
        by_elo: [{ name: 'claude', elo: 1520 }],
        by_calibration: [],
      };
      mockClient.getLeaderboardView.mockResolvedValueOnce(mockView);

      const result = await agentsApi.getLeaderboardView();

      expect(mockClient.getLeaderboardView).toHaveBeenCalledTimes(1);
      expect(result).toHaveProperty('by_elo');
    });
  });

  // ===========================================================================
  // Head-to-Head and Comparisons
  // ===========================================================================

  describe('Head-to-Head and Comparisons', () => {
    it('should get head-to-head stats', async () => {
      const mockH2H = {
        agent: 'claude',
        opponent: 'gpt-4',
        matches: 25,
        wins: 15,
        win_rate: 0.6,
      };
      mockClient.getAgentHeadToHead.mockResolvedValueOnce(mockH2H);

      const result = await agentsApi.getHeadToHead('claude', 'gpt-4');

      expect(mockClient.getAgentHeadToHead).toHaveBeenCalledWith('claude', 'gpt-4');
      expect(result.win_rate).toBe(0.6);
    });

    it('should get opponent briefing', async () => {
      const mockBriefing = {
        opponent: 'gpt-4',
        strengths: ['Strong reasoning'],
        weaknesses: ['Overconfident'],
      };
      mockClient.getAgentOpponentBriefing.mockResolvedValueOnce(mockBriefing);

      const result = await agentsApi.getOpponentBriefing('claude', 'gpt-4');

      expect(mockClient.getAgentOpponentBriefing).toHaveBeenCalledWith('claude', 'gpt-4');
      expect(result.strengths).toContain('Strong reasoning');
    });

    it('should compare multiple agents', async () => {
      const mockComparison = {
        agents: ['claude', 'gpt-4', 'gemini'],
        metrics: { elo: { claude: 1520, 'gpt-4': 1480 } },
      };
      mockClient.compareAgents.mockResolvedValueOnce(mockComparison);

      const result = await agentsApi.compare(['claude', 'gpt-4', 'gemini']);

      expect(mockClient.compareAgents).toHaveBeenCalledWith(['claude', 'gpt-4', 'gemini']);
      expect(result.agents).toHaveLength(3);
    });

    it('should compare two agents using compareAgents method', async () => {
      const mockComparison = {
        agents: ['claude', 'gpt-4'],
        metrics: {},
      };
      mockClient.compareAgents.mockResolvedValueOnce(mockComparison);

      const result = await agentsApi.compareAgents('claude', 'gpt-4');

      expect(mockClient.compareAgents).toHaveBeenCalledWith(['claude', 'gpt-4']);
      expect(result.agents).toContain('claude');
    });
  });

  // ===========================================================================
  // Team Selection
  // ===========================================================================

  describe('Team Selection', () => {
    it('should select a balanced team', async () => {
      const mockSelection = {
        agents: [
          { agent_id: 'claude', score: 0.95 },
          { agent_id: 'gpt-4', score: 0.88 },
        ],
        diversity_score: 0.85,
        total_score: 1.83,
      };
      mockClient.selectTeam.mockResolvedValueOnce(mockSelection);

      const result = await agentsApi.selectTeam('Design a distributed cache', 2, 'balanced');

      expect(mockClient.selectTeam).toHaveBeenCalledWith(
        expect.objectContaining({
          task_type: 'Design a distributed cache',
          team_size: 2,
          diversity_weight: 0.5,
          quality_weight: 0.5,
        })
      );
      expect(result.agents).toHaveLength(2);
    });

    it('should select a diverse team', async () => {
      mockClient.selectTeam.mockResolvedValueOnce({
        agents: [{ agent_id: 'claude' }, { agent_id: 'mistral' }],
        diversity_score: 0.95,
      });

      await agentsApi.selectTeam('Analyze market', 2, 'diverse');

      expect(mockClient.selectTeam).toHaveBeenCalledWith(
        expect.objectContaining({
          diversity_weight: 0.8,
          quality_weight: 0.2,
        })
      );
    });

    it('should select a competitive team', async () => {
      mockClient.selectTeam.mockResolvedValueOnce({
        agents: [{ agent_id: 'claude' }],
        diversity_score: 0.5,
      });

      await agentsApi.selectTeam('Code review', 1, 'competitive');

      expect(mockClient.selectTeam).toHaveBeenCalledWith(
        expect.objectContaining({
          diversity_weight: 0.2,
          quality_weight: 0.8,
        })
      );
    });

    it('should select a specialized team', async () => {
      mockClient.selectTeam.mockResolvedValueOnce({
        agents: [{ agent_id: 'claude' }],
        diversity_score: 0.3,
      });

      await agentsApi.selectTeam('Deep analysis', 1, 'specialized');

      expect(mockClient.selectTeam).toHaveBeenCalledWith(
        expect.objectContaining({
          diversity_weight: 0.0,
          quality_weight: 1.0,
        })
      );
    });
  });

  // ===========================================================================
  // Relationships
  // ===========================================================================

  describe('Relationships', () => {
    it('should get agent network', async () => {
      const mockNetwork = {
        agent: 'claude',
        connections: [{ agent: 'gemini', relationship: 'ally' }],
      };
      mockClient.getAgentNetwork.mockResolvedValueOnce(mockNetwork);

      const result = await agentsApi.getNetwork('claude');

      expect(mockClient.getAgentNetwork).toHaveBeenCalledWith('claude');
      expect(result.connections).toHaveLength(1);
    });

    it('should get agent relationships using alternate method', async () => {
      const mockNetwork = { agent: 'claude', connections: [] };
      mockClient.getAgentNetwork.mockResolvedValueOnce(mockNetwork);

      const result = await agentsApi.getRelationships('claude');

      expect(mockClient.getAgentNetwork).toHaveBeenCalledWith('claude');
      expect(result).toHaveProperty('connections');
    });

    it('should get allies', async () => {
      const mockAllies = {
        allies: [{ agent: 'gemini', agreement_rate: 0.85 }],
      };
      mockClient.getAgentAllies.mockResolvedValueOnce(mockAllies);

      const result = await agentsApi.getAllies('claude');

      expect(mockClient.getAgentAllies).toHaveBeenCalledWith('claude');
      expect(result.allies).toHaveLength(1);
    });

    it('should get rivals', async () => {
      const mockRivals = {
        rivals: [{ agent: 'gpt-4', rivalry_score: 0.75 }],
      };
      mockClient.getAgentRivals.mockResolvedValueOnce(mockRivals);

      const result = await agentsApi.getRivals('claude');

      expect(mockClient.getAgentRivals).toHaveBeenCalledWith('claude');
      expect(result.rivals).toHaveLength(1);
    });

    it('should get relationship between two agents', async () => {
      const mockRel = {
        agent_a: 'claude',
        agent_b: 'gpt-4',
        type: 'rival',
      };
      mockClient.getAgentRelationship.mockResolvedValueOnce(mockRel);

      const result = await agentsApi.getRelationship('claude', 'gpt-4');

      expect(mockClient.getAgentRelationship).toHaveBeenCalledWith('claude', 'gpt-4');
      expect(result.type).toBe('rival');
    });
  });

  // ===========================================================================
  // Flips and Positions
  // ===========================================================================

  describe('Flips and Positions', () => {
    it('should get agent flips', async () => {
      const mockFlips = {
        flips: [{ debate_id: 'd1', from_position: 'against', to_position: 'for' }],
      };
      mockClient.getAgentFlips.mockResolvedValueOnce(mockFlips);

      const result = await agentsApi.getFlips('claude', { limit: 10 });

      expect(mockClient.getAgentFlips).toHaveBeenCalledWith('claude', { limit: 10 });
      expect(result.flips).toHaveLength(1);
    });

    it('should get agent positions', async () => {
      const mockPositions = {
        positions: [{ topic: 'Microservices', position: 'for', confidence: 0.85 }],
      };
      mockClient.getAgentPositions.mockResolvedValueOnce(mockPositions);

      const result = await agentsApi.getPositions('claude', { topic: 'architecture' });

      expect(mockClient.getAgentPositions).toHaveBeenCalledWith('claude', { topic: 'architecture' });
      expect(result.positions).toHaveLength(1);
    });

    it('should get recent flips across all agents', async () => {
      const mockRecentFlips = {
        flips: [{ agent: 'claude', topic: 'Topic 1' }],
      };
      mockClient.getRecentFlips.mockResolvedValueOnce(mockRecentFlips);

      const result = await agentsApi.getRecentFlips({ limit: 10 });

      expect(mockClient.getRecentFlips).toHaveBeenCalledWith({ limit: 10 });
      expect(result.flips).toHaveLength(1);
    });

    it('should get flips summary', async () => {
      const mockSummary = { total_flips_today: 5 };
      mockClient.getFlipsSummary.mockResolvedValueOnce(mockSummary);

      const result = await agentsApi.getFlipsSummary();

      expect(mockClient.getFlipsSummary).toHaveBeenCalledTimes(1);
      expect(result).toHaveProperty('total_flips_today');
    });
  });

  // ===========================================================================
  // Domain and Reputation
  // ===========================================================================

  describe('Domain and Reputation', () => {
    it('should get agent domains', async () => {
      const mockDomains = {
        domains: [{ domain: 'software', elo: 1550, expertise_level: 'expert' }],
      };
      mockClient.getAgentDomains.mockResolvedValueOnce(mockDomains);

      const result = await agentsApi.getDomains('claude');

      expect(mockClient.getAgentDomains).toHaveBeenCalledWith('claude');
      expect(result.domains).toHaveLength(1);
    });

    it('should get agent reputation', async () => {
      mockClient.getAgentReputation.mockResolvedValueOnce({ reputation: 0.92 });

      const result = await agentsApi.getReputation('claude');

      expect(mockClient.getAgentReputation).toHaveBeenCalledWith('claude');
      expect(result.reputation).toBe(0.92);
    });

    it('should get agent moments', async () => {
      const mockMoments = {
        moments: [{ type: 'brilliant_argument', description: 'Great point' }],
      };
      mockClient.getAgentMoments.mockResolvedValueOnce(mockMoments);

      const result = await agentsApi.getMoments('claude', { type: 'brilliant', limit: 5 });

      expect(mockClient.getAgentMoments).toHaveBeenCalledWith('claude', { type: 'brilliant', limit: 5 });
      expect(result.moments).toHaveLength(1);
    });
  });

  // ===========================================================================
  // Registration and Lifecycle
  // ===========================================================================

  describe('Registration and Lifecycle', () => {
    it('should register a new agent', async () => {
      const mockResult = { agent_id: 'my-agent', registered: true };
      mockClient.request.mockResolvedValueOnce(mockResult);

      const result = await agentsApi.register('my-agent', {
        capabilities: ['debate', 'analysis'],
        model: 'gpt-4',
        provider: 'openai',
      });

      expect(mockClient.request).toHaveBeenCalledWith(
        'POST',
        '/api/v1/control-plane/agents',
        {
          body: {
            agent_id: 'my-agent',
            capabilities: ['debate', 'analysis'],
            model: 'gpt-4',
            provider: 'openai',
            metadata: {},
          },
        }
      );
      expect(result.agent_id).toBe('my-agent');
    });

    it('should unregister an agent', async () => {
      mockClient.request.mockResolvedValueOnce({ success: true, message: 'Unregistered' });

      const result = await agentsApi.unregister('my-agent');

      expect(mockClient.request).toHaveBeenCalledWith(
        'DELETE',
        '/api/v1/control-plane/agents/my-agent'
      );
      expect(result.success).toBe(true);
    });

    it('should send agent heartbeat', async () => {
      mockClient.request.mockResolvedValueOnce({ acknowledged: true, timestamp: '2024-01-01T00:00:00Z' });

      const result = await agentsApi.heartbeat('my-agent', 'healthy');

      expect(mockClient.request).toHaveBeenCalledWith(
        'POST',
        '/api/v1/control-plane/agents/my-agent/heartbeat',
        { body: { status: 'healthy' } }
      );
      expect(result.acknowledged).toBe(true);
    });
  });

  // ===========================================================================
  // Recent Data
  // ===========================================================================

  describe('Recent Data', () => {
    it('should get recent matches', async () => {
      const mockMatches = {
        matches: [{ id: 'm1', agents: ['claude', 'gpt-4'] }],
      };
      mockClient.getRecentMatches.mockResolvedValueOnce(mockMatches);

      const result = await agentsApi.getRecentMatches({ limit: 10 });

      expect(mockClient.getRecentMatches).toHaveBeenCalledWith({ limit: 10 });
      expect(result.matches).toHaveLength(1);
    });
  });
});
