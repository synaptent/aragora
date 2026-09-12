import { renderHook, act, waitFor } from '@testing-library/react';
import { useSupabaseHistory } from '@/hooks/useSupabaseHistory';
import {
  isSupabaseConfigured,
  fetchRecentLoops,
  fetchCyclesForLoop,
  fetchEventsForLoop,
  fetchDebatesForLoop,
  subscribeToEvents,
  subscribeToAllEvents,
} from '@/utils/supabase';

// Mock the supabase utilities
jest.mock('@/utils/supabase', () => ({
  supabase: {},
  isSupabaseConfigured: jest.fn(),
  fetchRecentLoops: jest.fn(),
  fetchCyclesForLoop: jest.fn(),
  fetchEventsForLoop: jest.fn(),
  fetchDebatesForLoop: jest.fn(),
  subscribeToEvents: jest.fn(),
  subscribeToAllEvents: jest.fn(),
}));

const mockIsSupabaseConfigured = isSupabaseConfigured as jest.MockedFunction<
  typeof isSupabaseConfigured
>;
const mockFetchRecentLoops = fetchRecentLoops as jest.MockedFunction<typeof fetchRecentLoops>;
const mockFetchCyclesForLoop = fetchCyclesForLoop as jest.MockedFunction<typeof fetchCyclesForLoop>;
const mockFetchEventsForLoop = fetchEventsForLoop as jest.MockedFunction<typeof fetchEventsForLoop>;
const mockFetchDebatesForLoop = fetchDebatesForLoop as jest.MockedFunction<
  typeof fetchDebatesForLoop
>;
const mockSubscribeToEvents = subscribeToEvents as jest.MockedFunction<typeof subscribeToEvents>;
const mockSubscribeToAllEvents = subscribeToAllEvents as jest.MockedFunction<
  typeof subscribeToAllEvents
>;

// Sample test data
const mockCycles = [
  { id: '1', loop_id: 'loop-1', cycle_number: 1, status: 'completed' },
  { id: '2', loop_id: 'loop-1', cycle_number: 2, status: 'running' },
];

const mockEvents = [
  { id: '1', loop_id: 'loop-1', event_type: 'cycle_start', created_at: new Date().toISOString() },
  { id: '2', loop_id: 'loop-1', event_type: 'debate_start', created_at: new Date().toISOString() },
];

const mockDebates = [{ id: '1', loop_id: 'loop-1', topic: 'AI Ethics', status: 'completed' }];

describe('useSupabaseHistory', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default to configured
    mockIsSupabaseConfigured.mockReturnValue(true);
    // Default subscriptions to return unsubscribe functions
    mockSubscribeToEvents.mockReturnValue(() => {});
    mockSubscribeToAllEvents.mockReturnValue(() => {});
  });

  describe('initial state', () => {
    it('should have expected initial data structures', async () => {
      mockFetchRecentLoops.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      // Initially starts with these defaults
      expect(result.current.recentLoops).toEqual([]);
      expect(result.current.selectedLoopId).toBeNull();
      expect(result.current.cycles).toEqual([]);
      expect(result.current.events).toEqual([]);
      expect(result.current.debates).toEqual([]);
      expect(result.current.error).toBeNull();

      // Wait for loading to complete
      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });
    });
  });

  describe('when Supabase is not configured', () => {
    it('should set isConfigured to false and stop loading', async () => {
      mockIsSupabaseConfigured.mockReturnValue(false);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isConfigured).toBe(false);
      expect(mockFetchRecentLoops).not.toHaveBeenCalled();
    });
  });

  describe('when Supabase is configured', () => {
    it('should set isConfigured to true', async () => {
      mockIsSupabaseConfigured.mockReturnValue(true);
      mockFetchRecentLoops.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isConfigured).toBe(true);
      });
    });

    it('should fetch recent loops on mount', async () => {
      const loops = ['loop-1', 'loop-2', 'loop-3'];
      mockFetchRecentLoops.mockResolvedValue(loops);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockFetchRecentLoops).toHaveBeenCalledWith(20);
      expect(result.current.recentLoops).toEqual(loops);
      // First loop is auto-selected
      expect(result.current.selectedLoopId).toBe('loop-1');
    });

    it('should handle empty loops list', async () => {
      mockFetchRecentLoops.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.recentLoops).toEqual([]);
      expect(result.current.selectedLoopId).toBeNull();
    });

    it('should handle error when fetching recent loops', async () => {
      mockFetchRecentLoops.mockRejectedValue(new Error('Network error'));

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.error).toBe('Error: Network error');
    });
  });

  describe('loading loop data', () => {
    it('should fetch cycles, events, and debates for selected loop', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue(mockCycles);
      mockFetchEventsForLoop.mockResolvedValue(mockEvents);
      mockFetchDebatesForLoop.mockResolvedValue(mockDebates);

      const { result } = renderHook(() => useSupabaseHistory());

      // Wait for all data to be loaded (cycles is populated)
      await waitFor(() => {
        expect(result.current.cycles.length).toBeGreaterThan(0);
      });

      expect(mockFetchCyclesForLoop).toHaveBeenCalledWith('loop-1');
      expect(mockFetchEventsForLoop).toHaveBeenCalledWith('loop-1');
      expect(mockFetchDebatesForLoop).toHaveBeenCalledWith('loop-1');

      expect(result.current.cycles).toEqual(mockCycles);
      expect(result.current.events).toEqual(mockEvents);
      expect(result.current.debates).toEqual(mockDebates);
    });

    it('should handle error when loading loop data', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockRejectedValue(new Error('Fetch failed'));
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.error).toBe('Error: Fetch failed');
      });

      expect(result.current.isLoading).toBe(false);
    });
  });

  describe('selectLoop', () => {
    it('should update selectedLoopId and clear previous data', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1', 'loop-2']);
      mockFetchCyclesForLoop.mockResolvedValue(mockCycles);
      mockFetchEventsForLoop.mockResolvedValue(mockEvents);
      mockFetchDebatesForLoop.mockResolvedValue(mockDebates);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
        expect(result.current.selectedLoopId).toBe('loop-1');
      });

      // Clear mocks and setup for second loop
      mockFetchCyclesForLoop.mockClear();
      mockFetchEventsForLoop.mockClear();
      mockFetchDebatesForLoop.mockClear();
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      act(() => {
        result.current.selectLoop('loop-2');
      });

      // Data should be cleared immediately
      expect(result.current.selectedLoopId).toBe('loop-2');
      expect(result.current.cycles).toEqual([]);
      expect(result.current.events).toEqual([]);
      expect(result.current.debates).toEqual([]);

      await waitFor(() => {
        expect(mockFetchCyclesForLoop).toHaveBeenCalledWith('loop-2');
      });
    });
  });

  describe('refresh', () => {
    it('should reload data for current loop', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue(mockCycles);
      mockFetchEventsForLoop.mockResolvedValue(mockEvents);
      mockFetchDebatesForLoop.mockResolvedValue(mockDebates);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Clear and setup new data
      const newCycles = [{ id: '3', loop_id: 'loop-1', cycle_number: 3, status: 'running' }];
      mockFetchCyclesForLoop.mockClear();
      mockFetchEventsForLoop.mockClear();
      mockFetchDebatesForLoop.mockClear();
      mockFetchCyclesForLoop.mockResolvedValue(newCycles);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      await act(async () => {
        await result.current.refresh();
      });

      expect(mockFetchCyclesForLoop).toHaveBeenCalledWith('loop-1');
      expect(result.current.cycles).toEqual(newCycles);
    });

    it('should do nothing if no loop is selected', async () => {
      mockFetchRecentLoops.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.refresh();
      });

      // No additional fetch calls beyond initial
      expect(mockFetchCyclesForLoop).not.toHaveBeenCalled();
    });

    it('should handle error during refresh', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue(mockCycles);
      mockFetchEventsForLoop.mockResolvedValue(mockEvents);
      mockFetchDebatesForLoop.mockResolvedValue(mockDebates);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Setup error for refresh
      mockFetchCyclesForLoop.mockRejectedValue(new Error('Refresh failed'));

      await act(async () => {
        await result.current.refresh();
      });

      expect(result.current.error).toBe('Error: Refresh failed');
      expect(result.current.isLoading).toBe(false);
    });
  });

  describe('real-time subscriptions', () => {
    it('should subscribe to events for selected loop', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockSubscribeToEvents).toHaveBeenCalledWith('loop-1', expect.any(Function));
    });

    it('should add new events from subscription to state', async () => {
      let eventCallback: ((event: unknown) => void) | null = null;
      mockSubscribeToEvents.mockImplementation((loopId, callback) => {
        eventCallback = callback;
        return () => {};
      });

      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      const newEvent = { id: 'new-1', loop_id: 'loop-1', event_type: 'test' };

      act(() => {
        eventCallback?.(newEvent);
      });

      expect(result.current.events).toContainEqual(newEvent);
    });

    it('should subscribe to all events to detect new loops', async () => {
      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(mockSubscribeToAllEvents).toHaveBeenCalled();
      });
    });

    it('should add new loop when event from unknown loop arrives', async () => {
      let allEventsCallback: ((event: { loop_id: string }) => void) | null = null;
      mockSubscribeToAllEvents.mockImplementation((callback) => {
        allEventsCallback = callback;
        return () => {};
      });

      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.recentLoops).toEqual(['loop-1']);

      act(() => {
        allEventsCallback?.({ loop_id: 'loop-new' });
      });

      expect(result.current.recentLoops).toContain('loop-new');
      expect(result.current.recentLoops[0]).toBe('loop-new'); // New loop at front
    });

    it('should not duplicate existing loop on all events', async () => {
      let allEventsCallback: ((event: { loop_id: string }) => void) | null = null;
      mockSubscribeToAllEvents.mockImplementation((callback) => {
        allEventsCallback = callback;
        return () => {};
      });

      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      act(() => {
        allEventsCallback?.({ loop_id: 'loop-1' });
      });

      // Should not duplicate
      expect(result.current.recentLoops.filter((l) => l === 'loop-1').length).toBe(1);
    });

    it('should unsubscribe from events on unmount', async () => {
      const unsubscribeEvents = jest.fn();
      const unsubscribeAllEvents = jest.fn();
      mockSubscribeToEvents.mockReturnValue(unsubscribeEvents);
      mockSubscribeToAllEvents.mockReturnValue(unsubscribeAllEvents);

      mockFetchRecentLoops.mockResolvedValue(['loop-1']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { unmount } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(mockSubscribeToEvents).toHaveBeenCalled();
      });

      unmount();

      expect(unsubscribeEvents).toHaveBeenCalled();
      expect(unsubscribeAllEvents).toHaveBeenCalled();
    });
  });

  describe('subscription cleanup on loop change', () => {
    it('should unsubscribe and resubscribe when loop changes', async () => {
      const unsubscribe1 = jest.fn();
      const unsubscribe2 = jest.fn();
      let callCount = 0;
      mockSubscribeToEvents.mockImplementation(() => {
        callCount++;
        return callCount === 1 ? unsubscribe1 : unsubscribe2;
      });

      mockFetchRecentLoops.mockResolvedValue(['loop-1', 'loop-2']);
      mockFetchCyclesForLoop.mockResolvedValue([]);
      mockFetchEventsForLoop.mockResolvedValue([]);
      mockFetchDebatesForLoop.mockResolvedValue([]);

      const { result } = renderHook(() => useSupabaseHistory());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockSubscribeToEvents).toHaveBeenCalledWith('loop-1', expect.any(Function));

      act(() => {
        result.current.selectLoop('loop-2');
      });

      await waitFor(() => {
        expect(mockSubscribeToEvents).toHaveBeenCalledWith('loop-2', expect.any(Function));
      });

      // Old subscription should be cleaned up
      expect(unsubscribe1).toHaveBeenCalled();
    });
  });
});
