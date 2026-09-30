import { renderHook, act } from '@testing-library/react';
import { useAgentRouting } from '@/hooks/useAgentRouting';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8080' }));

describe('useAgentRouting', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('starts with empty state', () => {
      const { result } = renderHook(() => useAgentRouting());

      expect(result.current.recommendations).toEqual([]);
      expect(result.current.recommendationsLoading).toBe(false);
      expect(result.current.recommendationsError).toBeNull();
      expect(result.current.autoRouteResult).toBeNull();
      expect(result.current.autoRouteLoading).toBe(false);
      expect(result.current.autoRouteError).toBeNull();
      expect(result.current.detectedDomains).toEqual([]);
      expect(result.current.domainLoading).toBe(false);
      expect(result.current.domainError).toBeNull();
      expect(result.current.bestTeams).toEqual([]);
      expect(result.current.bestTeamsLoading).toBe(false);
      expect(result.current.bestTeamsError).toBeNull();
      expect(result.current.domainLeaderboard).toEqual([]);
      expect(result.current.leaderboardLoading).toBe(false);
      expect(result.current.leaderboardError).toBeNull();
    });

    it('has correct computed values initially', () => {
      const { result } = renderHook(() => useAgentRouting());

      expect(result.current.hasRecommendations).toBe(false);
      expect(result.current.hasTeamResult).toBe(false);
      expect(result.current.primaryDomain).toBe('general');
    });
  });

  describe('getRecommendations', () => {
    it('fetches recommendations successfully', async () => {
      const mockRecommendations = [
        {
          agent: 'claude',
          score: 0.95,
          expertise: { programming: 0.9, debugging: 0.85 },
          traits: ['analytical', 'thorough'],
          rationale: 'Best for programming tasks',
        },
        {
          agent: 'gpt-4',
          score: 0.88,
          expertise: { programming: 0.85, creativity: 0.9 },
          traits: ['creative', 'versatile'],
        },
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ recommendations: mockRecommendations }),
      });

      const { result } = renderHook(() => useAgentRouting());

      let recommendations: unknown[];
      await act(async () => {
        recommendations = await result.current.getRecommendations({
          primary_domain: 'programming',
          limit: 5,
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/recommendations',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ primary_domain: 'programming', limit: 5 }),
        }),
      );
      expect(recommendations!).toEqual(mockRecommendations);
      expect(result.current.recommendations).toEqual(mockRecommendations);
      expect(result.current.recommendationsLoading).toBe(false);
      expect(result.current.hasRecommendations).toBe(true);
    });

    it('handles 503 service unavailable', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getRecommendations();
      });

      expect(result.current.recommendationsError).toBe('Agent routing unavailable');
      expect(result.current.recommendations).toEqual([]);
    });

    it('handles error response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ error: 'Invalid domain' }),
      });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getRecommendations({ primary_domain: 'invalid' });
      });

      expect(result.current.recommendationsError).toBe('Invalid domain');
    });

    it('handles network error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getRecommendations();
      });

      expect(result.current.recommendationsError).toBe('Network error');
    });

    it('shows loading state during request', async () => {
      mockFetch.mockImplementationOnce(() => new Promise(() => {}));

      const { result } = renderHook(() => useAgentRouting());

      act(() => {
        result.current.getRecommendations();
      });

      expect(result.current.recommendationsLoading).toBe(true);
    });
  });

  describe('autoRoute', () => {
    it('auto-routes task successfully', async () => {
      const mockResult = {
        task_id: 'task-123',
        detected_domain: { programming: 0.9, debugging: 0.7 },
        team: {
          agents: ['claude', 'gpt-4'],
          roles: { claude: 'lead', 'gpt-4': 'reviewer' },
          expected_quality: 0.92,
          diversity_score: 0.85,
        },
        rationale: 'Selected based on programming expertise',
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockResult });

      const { result } = renderHook(() => useAgentRouting());

      let autoRouteResult: unknown;
      await act(async () => {
        autoRouteResult = await result.current.autoRoute('Design a REST API', {
          task_id: 'task-123',
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/auto-route',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ task: 'Design a REST API', task_id: 'task-123' }),
        }),
      );
      expect(autoRouteResult).toEqual(mockResult);
      expect(result.current.autoRouteResult).toEqual(mockResult);
      expect(result.current.hasTeamResult).toBe(true);
    });

    it('handles 503 service unavailable', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => useAgentRouting());

      const autoRouteResult = await act(async () => {
        return await result.current.autoRoute('Test task');
      });

      expect(result.current.autoRouteError).toBe('Agent routing unavailable');
      expect(autoRouteResult).toBeNull();
    });

    it('supports exclude option', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          task_id: 'task-456',
          detected_domain: {},
          team: { agents: ['gemini'], roles: {}, expected_quality: 0.8, diversity_score: 0.5 },
          rationale: 'Excluded claude',
        }),
      });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.autoRoute('Test task', { exclude: ['claude', 'gpt-4'] });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/auto-route',
        expect.objectContaining({
          body: JSON.stringify({ task: 'Test task', exclude: ['claude', 'gpt-4'] }),
        }),
      );
    });
  });

  describe('detectDomain', () => {
    it('detects domains successfully', async () => {
      const mockDomains = [
        { domain: 'programming', confidence: 0.9 },
        { domain: 'debugging', confidence: 0.75 },
        { domain: 'architecture', confidence: 0.6 },
      ];

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ domains: mockDomains }) });

      const { result } = renderHook(() => useAgentRouting());

      let domains: unknown[];
      await act(async () => {
        domains = await result.current.detectDomain('How do I implement caching?', 3);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/detect-domain',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ task: 'How do I implement caching?', top_n: 3 }),
        }),
      );
      expect(domains!).toEqual(mockDomains);
      expect(result.current.detectedDomains).toEqual(mockDomains);
      expect(result.current.primaryDomain).toBe('programming');
    });

    it('handles 503 service unavailable', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.detectDomain('Test task');
      });

      expect(result.current.domainError).toBe('Domain detection unavailable');
    });

    it('returns general as primary domain when empty', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ domains: [] }) });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.detectDomain('Unknown task');
      });

      expect(result.current.primaryDomain).toBe('general');
    });
  });

  describe('getBestTeams', () => {
    it('fetches best teams successfully', async () => {
      const mockTeams = [
        { agents: ['claude', 'gpt-4'], win_rate: 0.85, debates: 50, avg_consensus_time: 120 },
        { agents: ['claude', 'gemini'], win_rate: 0.78, debates: 35, avg_consensus_time: 140 },
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ combinations: mockTeams }),
      });

      const { result } = renderHook(() => useAgentRouting());

      let teams: unknown[];
      await act(async () => {
        teams = await result.current.getBestTeams(5, 10);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/best-teams?min_debates=5&limit=10',
      );
      expect(teams!).toEqual(mockTeams);
      expect(result.current.bestTeams).toEqual(mockTeams);
    });

    it('handles 503 service unavailable', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getBestTeams();
      });

      expect(result.current.bestTeamsError).toBe('Team routing unavailable');
    });

    it('uses default parameters', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ combinations: [] }) });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getBestTeams();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/best-teams?min_debates=3&limit=10',
      );
    });
  });

  describe('getDomainLeaderboard', () => {
    it('fetches domain leaderboard successfully', async () => {
      const mockLeaderboard = [
        { agent: 'claude', score: 1850, wins: 45, losses: 12, expertise: { programming: 0.95 } },
        { agent: 'gpt-4', score: 1780, wins: 38, losses: 15, expertise: { programming: 0.88 } },
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ leaderboard: mockLeaderboard }),
      });

      const { result } = renderHook(() => useAgentRouting());

      let leaderboard: unknown[];
      await act(async () => {
        leaderboard = await result.current.getDomainLeaderboard('programming', 5);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/domain-leaderboard?domain=programming&limit=5',
      );
      expect(leaderboard!).toEqual(mockLeaderboard);
      expect(result.current.domainLeaderboard).toEqual(mockLeaderboard);
    });

    it('handles 503 service unavailable', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getDomainLeaderboard();
      });

      expect(result.current.leaderboardError).toBe('Leaderboard unavailable');
    });

    it('uses default parameters', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ leaderboard: [] }) });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getDomainLeaderboard();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/routing/domain-leaderboard?domain=general&limit=10',
      );
    });
  });

  describe('clearAutoRoute', () => {
    it('clears auto route state', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            task_id: 'task-123',
            detected_domain: { programming: 0.9 },
            team: { agents: ['claude'], roles: {}, expected_quality: 0.9, diversity_score: 0.5 },
            rationale: 'Test',
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ domains: [{ domain: 'programming', confidence: 0.9 }] }),
        });

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.autoRoute('Test task');
        await result.current.detectDomain('Test task');
      });

      expect(result.current.autoRouteResult).not.toBeNull();
      expect(result.current.detectedDomains.length).toBeGreaterThan(0);

      act(() => {
        result.current.clearAutoRoute();
      });

      expect(result.current.autoRouteResult).toBeNull();
      expect(result.current.autoRouteError).toBeNull();
      expect(result.current.detectedDomains).toEqual([]);
      expect(result.current.domainError).toBeNull();
    });
  });

  describe('clearErrors', () => {
    it('clears all errors', async () => {
      mockFetch.mockRejectedValue(new Error('Test error'));

      const { result } = renderHook(() => useAgentRouting());

      await act(async () => {
        await result.current.getRecommendations();
        await result.current.autoRoute('Test');
        await result.current.detectDomain('Test');
        await result.current.getBestTeams();
        await result.current.getDomainLeaderboard();
      });

      expect(result.current.recommendationsError).not.toBeNull();
      expect(result.current.autoRouteError).not.toBeNull();
      expect(result.current.domainError).not.toBeNull();
      expect(result.current.bestTeamsError).not.toBeNull();
      expect(result.current.leaderboardError).not.toBeNull();

      act(() => {
        result.current.clearErrors();
      });

      expect(result.current.recommendationsError).toBeNull();
      expect(result.current.autoRouteError).toBeNull();
      expect(result.current.domainError).toBeNull();
      expect(result.current.bestTeamsError).toBeNull();
      expect(result.current.leaderboardError).toBeNull();
    });
  });
});
