import { renderHook, act } from '@testing-library/react';
import { createHookWrapper } from '@/test-utils';
import { usePulseScheduler } from '@/hooks/usePulseScheduler';

// Provide an authenticated wrapper so useAuth() returns valid tokens
const hookWrapper = createHookWrapper({
  isAuthenticated: true,
  tokens: {
    access_token: 'test-token',
    refresh_token: 'test-refresh',
    token_type: 'bearer',
  } as never,
});

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockStatus = {
  state: 'stopped' as const,
  run_id: 'run-123',
  config: {
    poll_interval_seconds: 60,
    platforms: ['twitter', 'reddit'],
    max_debates_per_hour: 5,
    min_interval_between_debates: 300,
    min_volume_threshold: 100,
    min_controversy_score: 0.3,
    allowed_categories: ['tech', 'science'],
    blocked_categories: ['spam'],
    dedup_window_hours: 24,
    debate_rounds: 3,
    consensus_threshold: 0.7,
  },
  metrics: {
    polls_completed: 10,
    topics_evaluated: 50,
    topics_filtered: 45,
    debates_created: 5,
    debates_failed: 0,
    duplicates_skipped: 3,
    last_poll_at: Date.now() - 60000,
    last_debate_at: Date.now() - 3600000,
    uptime_seconds: 7200,
  },
  store_analytics: {
    total_debates: 100,
    consensus_rate: 0.85,
    avg_confidence: 0.72,
    by_platform: { twitter: 60, reddit: 40 },
  },
};

const mockHistory = {
  debates: [
    {
      id: 'debate-1',
      topic: 'AI regulation debate',
      platform: 'twitter',
      category: 'tech',
      volume: 1500,
      debate_id: 'full-debate-1',
      created_at: Date.now() - 3600000,
      hours_ago: 1,
      consensus_reached: true,
      confidence: 0.85,
      rounds_used: 3,
      scheduler_run_id: 'run-123',
    },
    {
      id: 'debate-2',
      topic: 'Climate policy discussion',
      platform: 'reddit',
      category: 'science',
      volume: 2000,
      debate_id: null,
      created_at: Date.now() - 7200000,
      hours_ago: 2,
      consensus_reached: null,
      confidence: null,
      rounds_used: 0,
      scheduler_run_id: 'run-123',
    },
  ],
  count: 2,
  total: 10,
  limit: 50,
  offset: 0,
};

describe('usePulseScheduler', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('initial state', () => {
    it('has correct initial state', () => {
      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      expect(result.current.status).toBeNull();
      expect(result.current.statusLoading).toBe(false);
      expect(result.current.statusError).toBeNull();
      expect(result.current.history).toEqual([]);
      expect(result.current.historyLoading).toBe(false);
      expect(result.current.historyTotal).toBe(0);
      expect(result.current.actionLoading).toBe(false);
      expect(result.current.actionError).toBeNull();
      expect(result.current.isRunning).toBe(false);
      expect(result.current.isPaused).toBe(false);
      expect(result.current.isStopped).toBe(false);
    });
  });

  describe('fetchStatus', () => {
    it('fetches and stores status', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.status).toEqual(mockStatus);
      expect(result.current.statusLoading).toBe(false);
      expect(result.current.statusError).toBeNull();
      expect(result.current.isStopped).toBe(true);
    });

    it('sets loading state during fetch', async () => {
      let resolvePromise: () => void;
      mockFetch.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolvePromise = () => resolve({ ok: true, json: () => Promise.resolve(mockStatus) });
          }),
      );

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      act(() => {
        result.current.fetchStatus();
      });

      expect(result.current.statusLoading).toBe(true);

      await act(async () => {
        resolvePromise!();
      });

      expect(result.current.statusLoading).toBe(false);
    });

    it('handles 503 as scheduler unavailable', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.statusError).toBe('Scheduler unavailable');
    });

    it('handles other HTTP errors', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.statusError).toBe('HTTP 500');
    });

    it('handles fetch failure', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.statusError).toBe('Network error');
    });
  });

  describe('polling', () => {
    it('starts polling at specified interval', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.startPolling(5000);
      });

      // Initial fetch
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Advance timer
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(2);

      // Advance again
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it('stops polling', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.startPolling(5000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);

      act(() => {
        result.current.stopPolling();
      });

      await act(async () => {
        jest.advanceTimersByTime(10000);
      });

      // Should not have made more calls
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('clears previous polling when starting new polling', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.startPolling(5000);
      });

      // Start new polling with different interval
      await act(async () => {
        result.current.startPolling(10000);
      });

      // Advance by 5s - should not trigger (old interval cleared)
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      // 2 initial fetches from starting polling twice
      expect(mockFetch).toHaveBeenCalledTimes(2);

      // Advance by 5 more seconds (total 10s) - should trigger new interval
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it('cleans up polling on unmount', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result, unmount } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.startPolling(5000);
      });

      unmount();

      // Advance timer - should not cause errors
      await act(async () => {
        jest.advanceTimersByTime(10000);
      });
    });
  });

  describe('scheduler actions', () => {
    describe('start', () => {
      it('sends start request and fetches status', async () => {
        mockFetch
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
          .mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ ...mockStatus, state: 'running' }),
          });

        const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

        let success: boolean = false;
        await act(async () => {
          success = await result.current.start();
        });

        expect(success).toBe(true);
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/pulse/scheduler/start'),
          expect.objectContaining({ method: 'POST' }),
        );
        expect(result.current.isRunning).toBe(true);
      });

      it('handles start failure', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: false,
          status: 400,
          json: () => Promise.resolve({ error: 'Already running' }),
        });

        const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

        let success: boolean = false;
        await act(async () => {
          success = await result.current.start();
        });

        expect(success).toBe(false);
        expect(result.current.actionError).toBe('Already running');
      });
    });

    describe('stop', () => {
      it('sends stop request with graceful flag', async () => {
        mockFetch
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockStatus) });

        const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

        await act(async () => {
          await result.current.stop(true);
        });

        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/pulse/scheduler/stop'),
          expect.objectContaining({ method: 'POST', body: JSON.stringify({ graceful: true }) }),
        );
      });

      it('sends stop request with graceful=false', async () => {
        mockFetch
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockStatus) });

        const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

        await act(async () => {
          await result.current.stop(false);
        });

        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/pulse/scheduler/stop'),
          expect.objectContaining({ body: JSON.stringify({ graceful: false }) }),
        );
      });
    });

    describe('pause', () => {
      it('sends pause request', async () => {
        mockFetch
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
          .mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ ...mockStatus, state: 'paused' }),
          });

        const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

        await act(async () => {
          await result.current.pause();
        });

        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/pulse/scheduler/pause'),
          expect.objectContaining({ method: 'POST' }),
        );
        expect(result.current.isPaused).toBe(true);
      });
    });

    describe('resume', () => {
      it('sends resume request', async () => {
        mockFetch
          .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
          .mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ ...mockStatus, state: 'running' }),
          });

        const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

        await act(async () => {
          await result.current.resume();
        });

        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/pulse/scheduler/resume'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });
  });

  describe('updateConfig', () => {
    it('sends config updates', async () => {
      mockFetch
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.updateConfig({ max_debates_per_hour: 10 });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/pulse/scheduler/config'),
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({ max_debates_per_hour: 10 }),
        }),
      );
    });

    it('handles config update failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ error: 'Invalid config' }),
      });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      const success = await act(async () => {
        return await result.current.updateConfig({ max_debates_per_hour: -1 });
      });

      expect(success).toBe(false);
      expect(result.current.actionError).toBe('Invalid config');
    });
  });

  describe('fetchHistory', () => {
    it('fetches debate history', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHistory) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchHistory();
      });

      expect(result.current.history).toEqual(mockHistory.debates);
      expect(result.current.historyTotal).toBe(10);
      expect(result.current.historyLoading).toBe(false);
    });

    it('fetches with pagination params', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHistory) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchHistory(20, 10);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('limit=20'),
        expect.anything(),
      );
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('offset=10'),
        expect.anything(),
      );
    });

    it('fetches with platform filter', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHistory) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchHistory(50, 0, 'twitter');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('platform=twitter'),
        expect.anything(),
      );
    });

    it('handles fetch history error', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchHistory();
      });

      expect(result.current.historyError).toBe('HTTP 500');
      expect(result.current.history).toEqual([]);
    });
  });

  describe('clearErrors', () => {
    it('clears all error states', async () => {
      mockFetch.mockRejectedValue(new Error('Test error'));

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      // Generate errors
      await act(async () => {
        await result.current.fetchStatus();
        await result.current.fetchHistory();
        await result.current.start();
      });

      expect(result.current.statusError).toBeTruthy();
      expect(result.current.historyError).toBeTruthy();
      expect(result.current.actionError).toBeTruthy();

      act(() => {
        result.current.clearErrors();
      });

      expect(result.current.statusError).toBeNull();
      expect(result.current.historyError).toBeNull();
      expect(result.current.actionError).toBeNull();
    });
  });

  describe('computed properties', () => {
    it('computes isRunning correctly', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ ...mockStatus, state: 'running' }),
      });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.isRunning).toBe(true);
      expect(result.current.isPaused).toBe(false);
      expect(result.current.isStopped).toBe(false);
    });

    it('computes isPaused correctly', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ ...mockStatus, state: 'paused' }),
      });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.isRunning).toBe(false);
      expect(result.current.isPaused).toBe(true);
      expect(result.current.isStopped).toBe(false);
    });

    it('exposes config and metrics shortcuts', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockStatus) });

      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.fetchStatus();
      });

      expect(result.current.config).toEqual(mockStatus.config);
      expect(result.current.metrics).toEqual(mockStatus.metrics);
    });

    it('returns null for config and metrics when no status', () => {
      const { result } = renderHook(() => usePulseScheduler(), { wrapper: hookWrapper });

      expect(result.current.config).toBeNull();
      expect(result.current.metrics).toBeNull();
    });
  });
});
