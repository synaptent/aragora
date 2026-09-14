/**
 * Replays Namespace Tests
 *
 * Comprehensive tests for the replays namespace API including:
 * - Replay listing
 * - Replay retrieval
 * - Events and evolution
 * - Forking
 * - Export and analysis
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { ReplaysAPI } from '../replays';

interface MockClient {
  request: Mock;
}

describe('ReplaysAPI Namespace', () => {
  let api: ReplaysAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
    };
    api = new ReplaysAPI(mockClient as any);
  });

  // ===========================================================================
  // Replay Listing
  // ===========================================================================

  describe('Replay Listing', () => {
    it('should list replays', async () => {
      const mockReplays = {
        replays: [
          {
            id: 'rp_1',
            debate_id: 'd_1',
            task: 'Microservices adoption',
            agents: ['claude', 'gpt-4'],
            total_rounds: 5,
            total_events: 50,
            duration_ms: 180000,
            result: 'consensus',
            created_at: '2024-01-20T10:00:00Z',
            size_bytes: 50000,
          },
        ],
        total: 1,
      };
      mockClient.request.mockResolvedValue(mockReplays);

      const result = await api.list();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays', { params: undefined });
      expect(result.replays).toHaveLength(1);
    });

    it('should list replays with filters', async () => {
      const mockReplays = { replays: [], total: 0 };
      mockClient.request.mockResolvedValue(mockReplays);

      await api.list({
        agent: 'claude',
        result: 'consensus',
        since: '2024-01-01',
        until: '2024-01-31',
        limit: 20,
        offset: 10,
      });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays', {
        params: {
          agent: 'claude',
          result: 'consensus',
          since: '2024-01-01',
          until: '2024-01-31',
          limit: 20,
          offset: 10,
        },
      });
    });
  });

  // ===========================================================================
  // Replay Retrieval
  // ===========================================================================

  describe('Replay Retrieval', () => {
    it('should get replay by ID', async () => {
      const mockReplay = {
        id: 'rp_1',
        debate_id: 'd_1',
        task: 'Microservices adoption',
        environment: { context: 'tech company' },
        protocol: { rounds: 5 },
        agents: ['claude', 'gpt-4'],
        events: [
          { id: 'e_1', type: 'debate_start', timestamp: 0 },
          { id: 'e_2', type: 'proposal', timestamp: 1000, agent: 'claude' },
        ],
        result: 'consensus',
        consensus_proposal: 'Adopt microservices gradually',
        total_tokens: 50000,
        created_at: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockReplay);

      const result = await api.get('rp_1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/rp_1');
      expect(result.events).toHaveLength(2);
    });

  });

  // ===========================================================================
  // Events
  // ===========================================================================

  describe('Events', () => {
    it('should get replay events', async () => {
      const mockEvents = {
        events: [
          { id: 'e_1', type: 'proposal', timestamp: 1000, agent: 'claude' },
          { id: 'e_2', type: 'critique', timestamp: 2000, agent: 'gpt-4' },
        ],
        total: 2,
      };
      mockClient.request.mockResolvedValue(mockEvents);

      const result = await api.getEvents('rp_1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/rp_1/events', { params: undefined });
      expect(result.events).toHaveLength(2);
    });

    it('should get events with filters', async () => {
      const mockEvents = { events: [], total: 0 };
      mockClient.request.mockResolvedValue(mockEvents);

      await api.getEvents('rp_1', {
        type: 'proposal',
        agent: 'claude',
        round: 2,
        limit: 10,
        offset: 5,
      });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/rp_1/events', {
        params: { type: 'proposal', agent: 'claude', round: 2, limit: 10, offset: 5 },
      });
    });
  });

  // ===========================================================================
  // Evolution
  // ===========================================================================

  describe('Evolution', () => {
    it('should get evolution data', async () => {
      const mockEvolution = {
        evolution: [
          {
            round: 1,
            timestamp: 0,
            proposals: [
              { agent: 'claude', content: 'Initial proposal', critique_count: 2, revision_count: 1, votes: 3 },
            ],
            convergence_score: 0.3,
            active_agents: ['claude', 'gpt-4'],
          },
          {
            round: 2,
            timestamp: 60000,
            proposals: [
              { agent: 'claude', content: 'Revised proposal', critique_count: 1, revision_count: 0, votes: 4 },
            ],
            convergence_score: 0.7,
            active_agents: ['claude', 'gpt-4'],
          },
        ],
      };
      mockClient.request.mockResolvedValue(mockEvolution);

      const result = await api.getEvolution('rp_1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/rp_1/evolution');
      expect(result.evolution).toHaveLength(2);
      expect(result.evolution[1].convergence_score).toBe(0.7);
    });
  });

  // ===========================================================================
  // Forking
  // ===========================================================================

  describe('Forking', () => {
    it('should fork replay', async () => {
      const mockFork = {
        id: 'fork_1',
        parent_replay_id: 'rp_1',
        fork_point: 60000,
        fork_round: 2,
        new_debate_id: 'd_new',
        created_at: '2024-01-20T11:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockFork);

      const result = await api.fork('rp_1', { fork_round: 2 });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/replays/rp_1/fork', {
        json: { fork_round: 2 },
      });
      expect(result.fork_round).toBe(2);
    });

    it('should fork with modifications', async () => {
      const mockFork = { id: 'fork_2', parent_replay_id: 'rp_1' };
      mockClient.request.mockResolvedValue(mockFork);

      await api.fork('rp_1', {
        fork_event_id: 'e_5',
        task_modification: 'Focus on security concerns',
        new_agents: ['claude', 'gemini'],
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/replays/rp_1/fork', {
        json: {
          fork_event_id: 'e_5',
          task_modification: 'Focus on security concerns',
          new_agents: ['claude', 'gemini'],
        },
      });
    });

    it('should list forks', async () => {
      const mockForks = {
        forks: [
          { id: 'fork_1', parent_replay_id: 'rp_1', fork_round: 2 },
          { id: 'fork_2', parent_replay_id: 'rp_1', fork_round: 3 },
        ],
      };
      mockClient.request.mockResolvedValue(mockForks);

      const result = await api.listForks('rp_1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/rp_1/forks');
      expect(result.forks).toHaveLength(2);
    });
  });

  // ===========================================================================
  // Export and Visualization
  // ===========================================================================

  describe('Export and Visualization', () => {
    it('should get HTML visualization', async () => {
      const mockHtml = '<html><body>Replay visualization</body></html>';
      mockClient.request.mockResolvedValue(mockHtml);

      const result = await api.getHtml('rp_1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/rp_1/html');
      expect(result).toContain('<html>');
    });

  });

  // ===========================================================================
  // Summary and Analysis
  // ===========================================================================

  describe('Summary and Analysis', () => {
    it('should compare replays', async () => {
      const mockComparison = {
        replay_1: { id: 'rp_1', task: 'Microservices', result: 'consensus' },
        replay_2: { id: 'rp_2', task: 'Monolith', result: 'no_consensus' },
        similarities: ['Both discussed architecture'],
        differences: ['Different outcomes', 'Different agent consensus'],
        agent_overlap: ['claude', 'gpt-4'],
        convergence_comparison: { replay_1: 0.85, replay_2: 0.45 },
      };
      mockClient.request.mockResolvedValue(mockComparison);

      const result = await api.compare('rp_1', 'rp_2');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/compare', {
        params: { replay_id_1: 'rp_1', replay_id_2: 'rp_2' },
      });
      expect(result.differences).toContain('Different outcomes');
    });

    it('should get replay stats', async () => {
      const mockStats = {
        total_replays: 500,
        total_events: 25000,
        average_duration_ms: 180000,
        consensus_rate: 0.75,
        average_rounds: 4.5,
        by_result: { consensus: 375, no_consensus: 100, timeout: 20, error: 5 },
      };
      mockClient.request.mockResolvedValue(mockStats);

      const result = await api.getStats({ period: '30d' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/stats', {
        params: { period: '30d' },
      });
      expect(result.consensus_rate).toBe(0.75);
    });

    it('should search replays', async () => {
      const mockResults = {
        results: [
          {
            replay_id: 'rp_1',
            task: 'Microservices',
            matches: [
              { event_id: 'e_5', content: 'scalability is key', highlight: '<em>scalability</em> is key' },
            ],
          },
        ],
      };
      mockClient.request.mockResolvedValue(mockResults);

      const result = await api.search('scalability', { in_proposals: true, limit: 10 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/replays/search', {
        params: { q: 'scalability', in_proposals: true, limit: 10 },
      });
      expect(result.results).toHaveLength(1);
    });
  });

  // ===========================================================================
  // Deletion
  // ===========================================================================

  describe('Deletion', () => {
    it('should delete replay', async () => {
      mockClient.request.mockResolvedValue({ success: true });

      const result = await api.delete('rp_1');

      expect(mockClient.request).toHaveBeenCalledWith('DELETE', '/api/replays/rp_1');
      expect(result.success).toBe(true);
    });
  });
});
