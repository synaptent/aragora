import { renderHook, act } from '@testing-library/react';
import { useNomicStream, fetchNomicState, fetchNomicLog } from '@/hooks/useNomicStream';

// Create a mock WebSocket class
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  url: string;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string; wasClean: boolean }) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = '') {
    this.readyState = 3;
    if (this.onclose) this.onclose({ code, reason, wasClean: true });
  }

  simulateOpen() {
    this.readyState = 1;
    if (this.onopen) this.onopen();
  }

  simulateMessage(data: object) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }

  simulateError() {
    if (this.onerror) this.onerror(new Event('error'));
  }

  simulateClose(code = 1000, reason = '') {
    this.readyState = 3;
    if (this.onclose) this.onclose({ code, reason, wasClean: code === 1000 });
  }
}

const originalWebSocket = global.WebSocket;

describe('useNomicStream', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.instances = [];
    const MockWSWithStatics = MockWebSocket as unknown as typeof WebSocket;
    Object.defineProperty(MockWSWithStatics, 'CONNECTING', { value: 0, writable: true });
    Object.defineProperty(MockWSWithStatics, 'OPEN', { value: 1, writable: true });
    Object.defineProperty(MockWSWithStatics, 'CLOSING', { value: 2, writable: true });
    Object.defineProperty(MockWSWithStatics, 'CLOSED', { value: 3, writable: true });
    (global as { WebSocket: unknown }).WebSocket = MockWSWithStatics;
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.clearAllTimers();
    // Close all mock WebSocket instances to prevent memory leaks
    MockWebSocket.instances.forEach((ws) => {
      if (ws.readyState !== 3) ws.readyState = 3;
    });
    MockWebSocket.instances = [];
    (global as { WebSocket: unknown }).WebSocket = originalWebSocket;
  });

  const getLatestWs = () => MockWebSocket.instances[MockWebSocket.instances.length - 1];

  describe('connection', () => {
    it('should connect to WebSocket on mount', () => {
      renderHook(() => useNomicStream('ws://test.ws'));

      expect(MockWebSocket.instances.length).toBe(1);
      expect(getLatestWs().url).toBe('ws://test.ws');
    });

    it('should set connected to true on open', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
      });

      expect(result.current.connected).toBe(true);
    });

    it('should set connected to false on close', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
      });

      expect(result.current.connected).toBe(true);

      act(() => {
        getLatestWs().simulateClose();
      });

      expect(result.current.connected).toBe(false);
    });

    it('should clean up on unmount', () => {
      const { unmount } = renderHook(() => useNomicStream());

      const ws = getLatestWs();
      act(() => {
        ws.simulateOpen();
      });

      unmount();

      expect(ws.readyState).toBe(3);
    });
  });

  describe('circuit breaker', () => {
    it('should reconnect with exponential backoff', () => {
      const { result } = renderHook(() => useNomicStream());

      const initialWs = getLatestWs();
      act(() => {
        initialWs.simulateClose();
      });

      expect(result.current.connected).toBe(false);

      // After 1 second, should reconnect (first backoff)
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      expect(MockWebSocket.instances.length).toBe(2);
    });

    it('should open circuit breaker after max attempts', () => {
      const { result } = renderHook(() => useNomicStream());

      // Simulate MAX_RECONNECT_ATTEMPTS (15) failures
      for (let i = 0; i < 15; i++) {
        act(() => {
          getLatestWs().simulateClose();
        });
        // Advance timer to trigger reconnect
        act(() => {
          jest.advanceTimersByTime(60000);
        });
      }

      // After 5 attempts, circuit should be open
      act(() => {
        getLatestWs().simulateClose();
      });

      expect(result.current.circuitOpen).toBe(true);
    });

    it('should reset circuit breaker on successful connection', () => {
      const { result } = renderHook(() => useNomicStream());

      // Simulate a few failed attempts
      act(() => {
        getLatestWs().simulateClose();
      });

      act(() => {
        jest.advanceTimersByTime(1000);
      });

      // Now successfully connect
      act(() => {
        getLatestWs().simulateOpen();
      });

      expect(result.current.connected).toBe(true);
      expect(result.current.circuitOpen).toBe(false);
    });

    it('should allow manual circuit breaker reset', () => {
      const { result } = renderHook(() => useNomicStream());

      // Force circuit open by exhausting attempts
      for (let i = 0; i < 16; i++) {
        act(() => {
          getLatestWs().simulateClose();
        });
        act(() => {
          jest.advanceTimersByTime(60000);
        });
      }

      expect(result.current.circuitOpen).toBe(true);

      // Reset circuit breaker
      act(() => {
        result.current.resetCircuitBreaker();
      });

      expect(result.current.circuitOpen).toBe(false);
      // Should have created a new WebSocket
      expect(MockWebSocket.instances.length).toBeGreaterThan(6);
    });
  });

  describe('event handling', () => {
    it('should handle sync event and set nomicState', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'sync', data: { cycle: 5, phase: 'running' } });
      });

      expect(result.current.nomicState).toEqual({ cycle: 5, phase: 'running' });
    });

    it('should add events to the events array', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'cycle_start', data: { cycle: 1 } });
      });

      expect(result.current.events.length).toBe(1);
      expect(result.current.events[0].type).toBe('cycle_start');
    });

    it('should limit events to MAX_EVENTS', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        // Send more than 5000 events
        for (let i = 0; i < 5100; i++) {
          getLatestWs().simulateMessage({ type: 'test_event', data: { index: i } });
        }
      });

      expect(result.current.events.length).toBeLessThanOrEqual(5000);
    });

    it('should clear events', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'test', data: {} });
        getLatestWs().simulateMessage({ type: 'test2', data: {} });
      });

      expect(result.current.events.length).toBe(2);

      act(() => {
        result.current.clearEvents();
      });

      expect(result.current.events.length).toBe(0);
    });
  });

  describe('state updates from events', () => {
    it('should update state on cycle_start', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'cycle_start', data: { cycle: 3 } });
      });

      expect(result.current.nomicState?.phase).toBe('starting');
      expect(result.current.nomicState?.cycle).toBe(3);
    });

    it('should update state on phase_start', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'phase_start', data: { phase: 'debate' } });
      });

      expect(result.current.nomicState?.phase).toBe('debate');
      expect(result.current.nomicState?.stage).toBe('running');
    });

    it('should update state on phase_end', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'phase_end', data: { success: true } });
      });

      expect(result.current.nomicState?.stage).toBe('complete');
    });

    it('should update state on task_complete', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'task_complete',
          data: { task_id: 'task-1', success: true },
        });
      });

      expect(result.current.nomicState?.completed_tasks).toBe(1);
      expect(result.current.nomicState?.last_task).toBe('task-1');
      expect(result.current.nomicState?.last_success).toBe(true);
    });

    it('should update state on cycle_end', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'cycle_end', data: { outcome: 'success' } });
      });

      expect(result.current.nomicState?.phase).toBe('complete');
      expect(result.current.nomicState?.stage).toBe('success');
    });
  });

  describe('loop management', () => {
    it('should handle loop_list event', () => {
      const { result } = renderHook(() => useNomicStream());

      const loops = [
        { loop_id: 'loop-1', name: 'Loop 1', started_at: 123, cycle: 1, phase: 'running' },
        { loop_id: 'loop-2', name: 'Loop 2', started_at: 456, cycle: 2, phase: 'idle' },
      ];

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'loop_list', data: { loops, count: 2 } });
      });

      expect(result.current.activeLoops).toEqual(loops);
      // First loop should be auto-selected
      expect(result.current.selectedLoopId).toBe('loop-1');
    });

    it('should handle loop_register event', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'loop_register',
          data: { loop_id: 'new-loop', name: 'New Loop', started_at: 789, path: '/path' },
        });
      });

      expect(result.current.activeLoops.length).toBe(1);
      expect(result.current.activeLoops[0].loop_id).toBe('new-loop');
      // Should be auto-selected as first loop
      expect(result.current.selectedLoopId).toBe('new-loop');
    });

    it('should handle loop_unregister event', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'loop_list',
          data: {
            loops: [
              { loop_id: 'loop-1', name: 'Loop 1' },
              { loop_id: 'loop-2', name: 'Loop 2' },
            ],
            count: 2,
          },
        });
      });

      expect(result.current.activeLoops.length).toBe(2);

      act(() => {
        getLatestWs().simulateMessage({ type: 'loop_unregister', data: { loop_id: 'loop-1' } });
      });

      expect(result.current.activeLoops.length).toBe(1);
      expect(result.current.activeLoops[0].loop_id).toBe('loop-2');
    });

    it('should allow manual loop selection', () => {
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'loop_list',
          data: {
            loops: [
              { loop_id: 'loop-1', name: 'Loop 1' },
              { loop_id: 'loop-2', name: 'Loop 2' },
            ],
            count: 2,
          },
        });
      });

      act(() => {
        result.current.selectLoop('loop-2');
      });

      expect(result.current.selectedLoopId).toBe('loop-2');
      // Events should be cleared on loop change
      expect(result.current.events.length).toBe(0);
    });

    it('should request loop list', () => {
      const { result } = renderHook(() => useNomicStream());

      const ws = getLatestWs();
      act(() => {
        ws.simulateOpen();
        result.current.requestLoopList();
      });

      const requestMessage = ws.sentMessages.find((m) => JSON.parse(m).type === 'get_loops');
      expect(requestMessage).toBeDefined();
    });
  });

  describe('messaging', () => {
    it('should send messages when connected', () => {
      const { result } = renderHook(() => useNomicStream());

      const ws = getLatestWs();
      act(() => {
        ws.simulateOpen();
        result.current.sendMessage({ type: 'test', data: { foo: 'bar' } });
      });

      expect(ws.sentMessages.length).toBe(1);
      expect(JSON.parse(ws.sentMessages[0])).toEqual({ type: 'test', data: { foo: 'bar' } });
    });

    it('should auto-inject loop_id for audience messages', () => {
      const { result } = renderHook(() => useNomicStream());

      const ws = getLatestWs();
      act(() => {
        ws.simulateOpen();
        // First set up a selected loop
        getLatestWs().simulateMessage({
          type: 'loop_register',
          data: { loop_id: 'active-loop', name: 'Active', started_at: 1, path: '/' },
        });
      });

      act(() => {
        result.current.sendMessage({ type: 'user_vote', data: { choice: 'A' } });
      });

      const voteMessage = JSON.parse(ws.sentMessages[0]);
      expect(voteMessage.loop_id).toBe('active-loop');
    });
  });

  describe('callbacks', () => {
    it('should call ack callbacks', () => {
      const ackCallback = jest.fn();
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        result.current.onAck(ackCallback);
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'ack', data: { msg_type: 'user_vote' } });
      });

      expect(ackCallback).toHaveBeenCalledWith('user_vote');
    });

    it('should call error callbacks', () => {
      const errorCallback = jest.fn();
      const { result } = renderHook(() => useNomicStream());

      act(() => {
        result.current.onError(errorCallback);
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'error', data: { message: 'Something went wrong' } });
      });

      expect(errorCallback).toHaveBeenCalledWith('Something went wrong');
    });

    it('should allow unsubscribing callbacks', () => {
      const callback = jest.fn();
      const { result } = renderHook(() => useNomicStream());

      let unsubscribe: () => void;
      act(() => {
        unsubscribe = result.current.onAck(callback);
      });

      act(() => {
        unsubscribe();
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'ack', data: { msg_type: 'test' } });
      });

      expect(callback).not.toHaveBeenCalled();
    });
  });
});

describe('fetchNomicState', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('should fetch state from API', async () => {
    const mockState = { cycle: 5, phase: 'running' };
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockState),
    });

    const state = await fetchNomicState('http://api.test');

    expect(global.fetch).toHaveBeenCalledWith('http://api.test/api/nomic/state', expect.anything());
    expect(state).toEqual(mockState);
  });

  it('should throw on error response', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 500 });

    await expect(fetchNomicState()).rejects.toThrow('Failed to fetch state: 500');
  });
});

describe('fetchNomicLog', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('should fetch log lines from API', async () => {
    const mockLines = ['line1', 'line2', 'line3'];
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ lines: mockLines }),
    });

    const lines = await fetchNomicLog('http://api.test', 50);

    expect(global.fetch).toHaveBeenCalledWith(
      'http://api.test/api/nomic/log?lines=50',
      expect.anything(),
    );
    expect(lines).toEqual(mockLines);
  });

  it('should return empty array if no lines', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const lines = await fetchNomicLog();

    expect(lines).toEqual([]);
  });

  it('should throw on error response', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 404 });

    await expect(fetchNomicLog()).rejects.toThrow('Failed to fetch log: 404');
  });
});
