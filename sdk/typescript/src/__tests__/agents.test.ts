/**
 * Agents Namespace Tests
 *
 * Tests for the agents namespace API including:
 * - Core listing and retrieval operations
 * - Agent profiles and performance metrics
 * - Calibration and ELO ratings
 * - Head-to-head matchups
 * - Team selection
 * - Agent relationships (allies, rivals)
 * - Registration and lifecycle management
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AragoraClient, createClient } from '../client';
import { AragoraError } from '../types';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('Agents Namespace', () => {
  let client: AragoraClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = createClient({
      baseUrl: 'https://api.aragora.ai',
      apiKey: 'test-api-key',
      retryEnabled: false,
    });
  });

  // ===========================================================================
  // Core Listing and Retrieval
  // ===========================================================================

  describe('Core Listing and Retrieval', () => {
    it('should list all agents', async () => {
      const mockAgents = {
        agents: [
          { name: 'claude', elo: 1520, matches: 100, wins: 60 },
          { name: 'gpt-4', elo: 1480, matches: 95, wins: 52 },
          { name: 'gemini', elo: 1450, matches: 80, wins: 40 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockAgents)),
      });

      const result = await client.agents.list();

      expect(result.agents).toHaveLength(3);
      expect(result.agents[0].name).toBe('claude');
      expect(result.agents[0].elo).toBe(1520);
    });

    it('should get a specific agent', async () => {
      const mockAgent = {
        name: 'claude',
        elo: 1520,
        matches: 100,
        wins: 60,
        losses: 40,
        calibration_score: 0.92,
        domains: ['software', 'strategy'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockAgent)),
      });

      const result = await client.agents.get('claude');

      expect(result.name).toBe('claude');
      expect(result.elo).toBe(1520);
      expect(result.domains).toContain('software');
    });

    it('should get agent availability', async () => {
      const mockAvailability = {
        available: ['claude', 'gpt-4', 'gemini'],
        missing: ['llama'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockAvailability)),
      });

      const result = await client.agents.getAvailability();

      expect(result.available).toContain('claude');
      expect(result.missing).toContain('llama');
    });

    it('should get agent health status', async () => {
      const mockHealth = {
        claude: { status: 'healthy', latency_ms: 120 },
        'gpt-4': { status: 'healthy', latency_ms: 150 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockHealth)),
      });

      const result = await client.agents.getHealth();

      expect(result).toHaveProperty('claude');
    });

    it('should list local agents', async () => {
      const mockLocalAgents = {
        agents: ['claude-local', 'codex-local'],
        count: 2,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockLocalAgents)),
      });

      const result = await client.agents.listLocal();

      expect(result).toHaveProperty('agents');
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
        matches: 100,
        wins: 60,
        reputation: 0.92,
        consistency_score: 0.88,
        flip_rate: 0.12,
        allies: ['gemini'],
        rivals: ['gpt-4'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockProfile)),
      });

      const result = await client.agents.getProfile('claude');

      expect(result.reputation).toBe(0.92);
      expect(result.allies).toContain('gemini');
    });

    it('should get agent persona', async () => {
      const mockPersona = {
        agent_name: 'claude',
        description: 'A helpful AI assistant',
        traits: ['analytical', 'thorough'],
        expertise: ['software engineering', 'strategy'],
        model: 'claude-3-opus',
        temperature: 0.7,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockPersona)),
      });

      const result = await client.agents.getPersona('claude');

      expect(result.agent_name).toBe('claude');
      expect(result.traits).toContain('analytical');
    });

    it('should get grounded persona', async () => {
      const mockGroundedPersona = {
        agent_name: 'claude',
        elo: 1520,
        domain_elos: { software: 1550, strategy: 1490 },
        win_rate: 0.6,
        calibration_score: 0.92,
        position_accuracy: 0.85,
        debates_count: 100,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockGroundedPersona)),
      });

      const result = await client.agents.getGroundedPersona('claude');

      expect(result.elo).toBe(1520);
      expect(result.domain_elos.software).toBe(1550);
    });

    it('should get identity prompt', async () => {
      const mockIdentity = {
        agent_name: 'claude',
        prompt: 'You are Claude, an AI assistant...',
        sections_included: ['role', 'capabilities', 'constraints'],
        token_count: 250,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockIdentity)),
      });

      const result = await client.agents.getIdentityPrompt('claude');

      expect(result.prompt).toContain('Claude');
      expect(result.token_count).toBe(250);
    });

    it('should get agent metadata', async () => {
      const mockMetadata = {
        model: 'claude-3-opus',
        provider: 'anthropic',
        version: '2024-01-01',
        capabilities: ['reasoning', 'coding', 'analysis'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockMetadata)),
      });

      const result = await client.agents.getMetadata('claude');

      expect(result).toHaveProperty('model');
    });
  });

  // ===========================================================================
  // Performance and Calibration
  // ===========================================================================

  describe('Performance and Calibration', () => {
    it('should get agent performance stats', async () => {
      const mockPerformance = {
        agent: 'claude',
        elo: 1520,
        matches: 100,
        wins: 60,
        losses: 40,
        win_rate: 0.6,
        avg_confidence: 0.85,
        avg_accuracy: 0.88,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockPerformance)),
      });

      const result = await client.agents.getPerformance('claude');

      expect(result.win_rate).toBe(0.6);
      expect(result.avg_confidence).toBe(0.85);
    });

    it('should get agent calibration', async () => {
      const mockCalibration = {
        agent: 'claude',
        score: 0.92,
        brier_score: 0.08,
        overconfidence: -0.02,
        samples: 500,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockCalibration)),
      });

      const result = await client.agents.getCalibration('claude');

      expect(result.score).toBe(0.92);
    });

    it('should get calibration curve', async () => {
      const mockCurve = {
        agent: 'claude',
        buckets: [
          { predicted: 0.1, actual: 0.08, count: 50 },
          { predicted: 0.5, actual: 0.52, count: 100 },
          { predicted: 0.9, actual: 0.88, count: 80 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockCurve)),
      });

      const result = await client.agents.getCalibrationCurve('claude');

      expect(result).toHaveProperty('buckets');
    });

    it('should get the auditable calibration report', async () => {
      const mockReport = {
        agent: 'claude',
        status: 'ok',
        sample_size: 12,
        overall: { sample_size: 12, accuracy: 0.75, brier_score: 0.18 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockReport)),
      });

      const result = await client.agents.getCalibrationReport('claude');

      expect(result.status).toBe('ok');
      expect(result.sample_size).toBe(12);
      const calledUrl = mockFetch.mock.calls[mockFetch.mock.calls.length - 1][0] as string;
      expect(calledUrl).toContain('/api/v1/agents/claude/calibration-report');
    });

    it('should surface the explicit absent contract in the calibration report', async () => {
      const mockReport = {
        agent: 'ghost',
        status: 'absent',
        reason: 'no calibration data recorded for this agent',
        sample_size: 0,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockReport)),
      });

      const result = await client.agents.getCalibrationReport('ghost');

      expect(result.status).toBe('absent');
      expect(result.sample_size).toBe(0);
    });

    it('should get agent consistency', async () => {
      const mockConsistency = {
        agent: 'claude',
        overall_score: 0.88,
        position_stability: 0.85,
        reasoning_consistency: 0.91,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockConsistency)),
      });

      const result = await client.agents.getConsistency('claude');

      expect(result.overall_score).toBe(0.88);
    });

    it('should get agent accuracy', async () => {
      const mockAccuracy = {
        agent_name: 'claude',
        total_positions: 500,
        verified_positions: 400,
        correct_positions: 340,
        accuracy_rate: 0.85,
        by_domain: {
          software: { total: 200, correct: 180, accuracy: 0.9 },
          strategy: { total: 150, correct: 120, accuracy: 0.8 },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockAccuracy)),
      });

      const result = await client.agents.getAccuracy('claude');

      expect(result.accuracy_rate).toBe(0.85);
      expect(result.by_domain?.software.accuracy).toBe(0.9);
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
        history: [
          { date: '2024-01-01', elo: 1500 },
          { date: '2024-01-15', elo: 1510 },
          { date: '2024-01-30', elo: 1520 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockElo)),
      });

      const result = await client.agents.getElo('claude');

      expect(result.elo).toBe(1520);
      expect(result.history).toHaveLength(3);
    });

    it('should get leaderboard', async () => {
      const mockLeaderboard = {
        agents: [
          { name: 'claude', elo: 1520, matches: 100 },
          { name: 'gpt-4', elo: 1480, matches: 95 },
          { name: 'gemini', elo: 1450, matches: 80 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockLeaderboard)),
      });

      const result = await client.agents.getLeaderboard();

      expect(result.agents).toHaveLength(3);
      expect(result.agents[0].name).toBe('claude');
    });

    it('should get rankings with filters', async () => {
      const mockRankings = {
        rankings: [
          { agent: 'claude', elo: 1550, rank: 1 },
          { agent: 'gpt-4', elo: 1490, rank: 2 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRankings)),
      });

      const result = await client.agents.getRankings({
        domain: 'software',
        limit: 10,
        sortBy: 'elo',
      });

      expect(result.rankings).toHaveLength(2);
      expect(result.rankings[0].rank).toBe(1);
    });

    it('should update agent ELO', async () => {
      const mockUpdate = {
        agent: 'claude',
        elo: 1530,
        previous_elo: 1520,
        change: 10,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockUpdate)),
      });

      const result = await client.agents.updateElo('claude', 10, {
        debateId: 'debate-123',
        reason: 'Won debate',
      });

      expect(result.elo).toBe(1530);
      expect(result.change).toBe(10);
    });

    it('should get calibration leaderboard', async () => {
      const mockCalibrationLeaderboard = {
        agents: [
          { name: 'claude', score: 0.95 },
          { name: 'gemini', score: 0.92 },
          { name: 'gpt-4', score: 0.88 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockCalibrationLeaderboard)),
      });

      const result = await client.agents.getCalibrationLeaderboard();

      expect(result.agents).toHaveLength(3);
      expect(result.agents[0].score).toBe(0.95);
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
        losses: 10,
        win_rate: 0.6,
        avg_elo_gain: 5,
        domains: {
          software: { wins: 10, losses: 3 },
          strategy: { wins: 5, losses: 7 },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockH2H)),
      });

      const result = await client.agents.getHeadToHead('claude', 'gpt-4');

      expect(result.win_rate).toBe(0.6);
      expect(result.matches).toBe(25);
    });

    it('should get opponent briefing', async () => {
      const mockBriefing = {
        opponent: 'gpt-4',
        strengths: ['Strong reasoning', 'Detailed analysis'],
        weaknesses: ['Sometimes overconfident', 'May miss edge cases'],
        recommended_strategy: 'Focus on concrete examples',
        historical_performance: { wins: 15, losses: 10 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockBriefing)),
      });

      const result = await client.agents.getOpponentBriefing('claude', 'gpt-4');

      expect(result.strengths).toContain('Strong reasoning');
    });

    it('should compare multiple agents', async () => {
      const mockComparison = {
        agents: ['claude', 'gpt-4', 'gemini'],
        metrics: {
          elo: { claude: 1520, 'gpt-4': 1480, gemini: 1450 },
          win_rate: { claude: 0.6, 'gpt-4': 0.55, gemini: 0.5 },
          calibration: { claude: 0.92, 'gpt-4': 0.88, gemini: 0.85 },
        },
        winner_by_metric: {
          elo: 'claude',
          win_rate: 'claude',
          calibration: 'claude',
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockComparison)),
      });

      const result = await client.agents.compare(['claude', 'gpt-4', 'gemini']);

      expect(result.agents).toHaveLength(3);
    });

    it('should compare two agents using compareAgents', async () => {
      const mockComparison = {
        agents: ['claude', 'gpt-4'],
        metrics: {
          elo: { claude: 1520, 'gpt-4': 1480 },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockComparison)),
      });

      const result = await client.agents.compareAgents('claude', 'gpt-4');

      expect(result.agents).toContain('claude');
      expect(result.agents).toContain('gpt-4');
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
          { agent_id: 'gemini', score: 0.82 },
        ],
        diversity_score: 0.85,
        total_score: 2.65,
        coverage: {
          software: ['claude', 'gpt-4'],
          strategy: ['gemini', 'claude'],
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockSelection)),
      });

      const result = await client.agents.selectTeam('Design a distributed cache', 3, 'balanced');

      expect(result.agents).toHaveLength(3);
      expect(result.diversity_score).toBe(0.85);
    });

    it('should select a diverse team', async () => {
      const mockSelection = {
        agents: [
          { agent_id: 'claude', score: 0.9 },
          { agent_id: 'mistral', score: 0.8 },
          { agent_id: 'deepseek', score: 0.75 },
        ],
        diversity_score: 0.95,
        total_score: 2.45,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockSelection)),
      });

      const result = await client.agents.selectTeam('Analyze market trends', 3, 'diverse');

      expect(result.agents).toHaveLength(3);
      expect(result.diversity_score).toBe(0.95);
    });

    it('should select a competitive team', async () => {
      const mockSelection = {
        agents: [
          { agent_id: 'claude', score: 0.98 },
          { agent_id: 'gpt-4', score: 0.95 },
        ],
        diversity_score: 0.6,
        total_score: 1.93,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockSelection)),
      });

      const result = await client.agents.selectTeam('Code review', 2, 'competitive');

      expect(result.agents).toHaveLength(2);
    });
  });

  // ===========================================================================
  // Relationships (Allies and Rivals)
  // ===========================================================================

  describe('Relationships', () => {
    it('should get agent network', async () => {
      const mockNetwork = {
        agent: 'claude',
        connections: [
          { agent: 'gemini', relationship: 'ally', strength: 0.8 },
          { agent: 'gpt-4', relationship: 'rival', strength: 0.7 },
        ],
        total_allies: 3,
        total_rivals: 2,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockNetwork)),
      });

      const result = await client.agents.getNetwork('claude');

      expect(result.connections).toHaveLength(2);
    });

    it('should get allies', async () => {
      const mockAllies = {
        allies: [
          { agent: 'gemini', agreement_rate: 0.85, shared_wins: 15 },
          { agent: 'mistral', agreement_rate: 0.78, shared_wins: 10 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockAllies)),
      });

      const result = await client.agents.getAllies('claude');

      expect(result.allies).toHaveLength(2);
    });

    it('should get rivals', async () => {
      const mockRivals = {
        rivals: [
          { agent: 'gpt-4', rivalry_score: 0.75, head_to_head: { wins: 15, losses: 10 } },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRivals)),
      });

      const result = await client.agents.getRivals('claude');

      expect(result.rivals).toHaveLength(1);
    });

    it('should get relationship between two agents', async () => {
      const mockRelationship = {
        agent_a: 'claude',
        agent_b: 'gpt-4',
        type: 'rival',
        agreement_rate: 0.45,
        total_debates: 25,
        dynamics: 'competitive',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRelationship)),
      });

      const result = await client.agents.getRelationship('claude', 'gpt-4');

      expect(result.type).toBe('rival');
    });

    it('should get relationships using alternate method', async () => {
      const mockNetwork = {
        agent: 'claude',
        connections: [
          { agent: 'gemini', relationship: 'ally', strength: 0.8 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockNetwork)),
      });

      const result = await client.agents.getRelationships('claude');

      expect(result).toHaveProperty('connections');
    });
  });

  // ===========================================================================
  // Flips and Positions
  // ===========================================================================

  describe('Flips and Positions', () => {
    it('should get agent flips', async () => {
      const mockFlips = {
        flips: [
          {
            debate_id: 'debate-123',
            topic: 'Microservices',
            from_position: 'against',
            to_position: 'for',
            round: 3,
            reason: 'Convinced by evidence',
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockFlips)),
      });

      const result = await client.agents.getFlips('claude', { limit: 10 });

      expect(result.flips).toHaveLength(1);
      expect(result.flips[0].from_position).toBe('against');
    });

    it('should get agent positions', async () => {
      const mockPositions = {
        positions: [
          { topic: 'Microservices', position: 'for', confidence: 0.85, debates: 5 },
          { topic: 'Monolith', position: 'against', confidence: 0.7, debates: 3 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockPositions)),
      });

      const result = await client.agents.getPositions('claude', { topic: 'architecture' });

      expect(result.positions).toHaveLength(2);
    });

    it('should get recent flips across all agents', async () => {
      const mockRecentFlips = {
        flips: [
          { agent: 'claude', topic: 'Topic 1', timestamp: '2024-01-01T00:00:00Z' },
          { agent: 'gpt-4', topic: 'Topic 2', timestamp: '2024-01-01T00:01:00Z' },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRecentFlips)),
      });

      const result = await client.agents.getRecentFlips({ limit: 10 });

      expect(result.flips).toHaveLength(2);
    });

    it('should get flips summary', async () => {
      const mockSummary = {
        total_flips_today: 5,
        agents_with_flips: ['claude', 'gpt-4'],
        top_topics: ['AI safety', 'Cloud computing'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockSummary)),
      });

      const result = await client.agents.getFlipsSummary();

      expect(result).toHaveProperty('total_flips_today');
    });
  });

  // ===========================================================================
  // Domain and Reputation
  // ===========================================================================

  describe('Domain and Reputation', () => {
    it('should get agent domains', async () => {
      const mockDomains = {
        domains: [
          { domain: 'software', elo: 1550, expertise_level: 'expert' },
          { domain: 'strategy', elo: 1490, expertise_level: 'advanced' },
          { domain: 'security', elo: 1420, expertise_level: 'intermediate' },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockDomains)),
      });

      const result = await client.agents.getDomains('claude');

      expect(result.domains).toHaveLength(3);
      expect(result.domains[0].domain).toBe('software');
    });

    it('should get agent reputation', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ reputation: 0.92 })),
      });

      const result = await client.agents.getReputation('claude');

      expect(result.reputation).toBe(0.92);
    });

    it('should get agent moments', async () => {
      const mockMoments = {
        moments: [
          {
            type: 'brilliant_argument',
            description: 'Made a compelling case for microservices',
            debate_id: 'debate-123',
            timestamp: '2024-01-01T00:00:00Z',
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockMoments)),
      });

      const result = await client.agents.getMoments('claude', { type: 'brilliant', limit: 5 });

      expect(result.moments).toHaveLength(1);
    });
  });

  // ===========================================================================
  // Agent Registration and Lifecycle
  // ===========================================================================

  describe('Agent Registration and Lifecycle', () => {
    it('should register a new agent', async () => {
      const mockRegistration = {
        agent_id: 'my-agent',
        registered: true,
        created_at: '2024-01-01T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRegistration)),
      });

      const result = await client.agents.register('my-agent', {
        capabilities: ['debate', 'analysis'],
        model: 'gpt-4',
        provider: 'openai',
      });

      expect(result.agent_id).toBe('my-agent');
    });

    it('should unregister an agent', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ success: true, message: 'Agent unregistered' })),
      });

      const result = await client.agents.unregister('my-agent');

      expect(result.success).toBe(true);
    });

    it('should send agent heartbeat', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          acknowledged: true,
          timestamp: '2024-01-01T00:00:00Z',
        })),
      });

      const result = await client.agents.heartbeat('my-agent', 'healthy');

      expect(result.acknowledged).toBe(true);
    });
  });

  // ===========================================================================
  // History and Matches
  // ===========================================================================

  describe('History and Matches', () => {
    it('should get agent history', async () => {
      const mockHistory = {
        matches: [
          { debate_id: 'd1', opponent: 'gpt-4', result: 'win', elo_change: 10 },
          { debate_id: 'd2', opponent: 'gemini', result: 'loss', elo_change: -8 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockHistory)),
      });

      const result = await client.agents.getHistory('claude', { limit: 10 });

      expect(result.matches).toHaveLength(2);
    });

    it('should get recent matches', async () => {
      const mockMatches = {
        matches: [
          { id: 'm1', agents: ['claude', 'gpt-4'], winner: 'claude' },
          { id: 'm2', agents: ['gemini', 'mistral'], winner: 'gemini' },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockMatches)),
      });

      const result = await client.agents.getRecentMatches({ limit: 10 });

      expect(result.matches).toHaveLength(2);
    });
  });

  // ===========================================================================
  // Error Handling
  // ===========================================================================

  describe('Error Handling', () => {
    it('should handle 404 for non-existent agent', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: () => Promise.resolve({
          error: 'Agent not found',
          code: 'NOT_FOUND',
        }),
      });

      await expect(client.agents.get('nonexistent'))
        .rejects.toThrow('Agent not found');
    });

    it('should handle permission errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 403,
        json: () => Promise.resolve({
          error: 'Access denied',
          code: 'FORBIDDEN',
        }),
      });

      await expect(client.agents.register('protected-agent'))
        .rejects.toThrow('Access denied');
    });

    it('should handle server errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({
          error: 'Internal server error',
          code: 'INTERNAL_ERROR',
        }),
      });

      await expect(client.agents.list())
        .rejects.toThrow('Internal server error');
    });
  });

  // ===========================================================================
  // Introspection and Stats
  // ===========================================================================

  describe('Introspection and Stats', () => {
    it('should get agent introspection', async () => {
      const mockIntrospection = {
        self_awareness: 0.85,
        uncertainty_calibration: 0.9,
        meta_reasoning: 0.88,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockIntrospection)),
      });

      const result = await client.agents.getIntrospection('claude');

      expect(result).toHaveProperty('self_awareness');
    });

    it('should get leaderboard view', async () => {
      const mockView = {
        by_elo: [{ name: 'claude', elo: 1520 }],
        by_calibration: [{ name: 'gemini', score: 0.95 }],
        by_win_rate: [{ name: 'gpt-4', win_rate: 0.65 }],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockView)),
      });

      const result = await client.agents.getLeaderboardView();

      expect(result).toHaveProperty('by_elo');
    });
  });
});
