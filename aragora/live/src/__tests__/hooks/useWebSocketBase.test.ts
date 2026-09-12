import { renderHook, act } from '@testing-library/react';
import {
  useWebSocketBase,
  validateWsUrl,
  MAX_RECONNECT_ATTEMPTS,
  MAX_RECONNECT_DELAY_MS,
} from '@/hooks/useWebSocketBase';

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  url: string;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
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
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code, reason });
  }

  // Test helpers
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
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
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code, reason });
  }
}

// Get the latest WebSocket instance
function getLatestWs(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

// Setup and teardown
beforeAll(() => {
  (global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;
  jest.useFakeTimers();
});

afterAll(() => {
  jest.useRealTimers();
});

beforeEach(() => {
  MockWebSocket.instances = [];
  jest.clearAllMocks();
  jest.clearAllTimers();
});

describe('validateWsUrl', () => {
  it('rejects empty URL', () => {
    const result = validateWsUrl('');
    expect(result.valid).toBe(false);
    expect(result.error).toBe('WebSocket URL is required');
  });

  it('rejects http:// protocol', () => {
    const result = validateWsUrl('http://example.com');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('Invalid WebSocket URL protocol');
  });

  it('rejects https:// protocol', () => {
    const result = validateWsUrl('https://example.com');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('Invalid WebSocket URL protocol');
  });

  it('accepts ws:// protocol', () => {
    const result = validateWsUrl('ws://example.com');
    expect(result.valid).toBe(true);
    expect(result.error).toBeUndefined();
  });

  it('accepts wss:// protocol', () => {
    const result = validateWsUrl('wss://example.com/socket');
    expect(result.valid).toBe(true);
    expect(result.error).toBeUndefined();
  });

  it('rejects invalid URL format', () => {
    const result = validateWsUrl('ws://[invalid');
    expect(result.valid).toBe(false);
    expect(result.error).toBe('Invalid WebSocket URL format');
  });
});

describe('useWebSocketBase', () => {
  describe('initial state', () => {
    it('starts disconnected when enabled', () => {
      const { result } = renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws' }));

      // Initially connecting
      expect(result.current.status).toBe('connecting');
      expect(result.current.error).toBeNull();
      expect(result.current.isConnected).toBe(false);
      expect(result.current.reconnectAttempt).toBe(0);
    });

    it('stays disconnected when disabled', () => {
      const { result } = renderHook(() =>
        useWebSocketBase({ wsUrl: 'wss://test.com/ws', enabled: false }),
      );

      expect(result.current.status).toBe('disconnected');
      expect(result.current.isConnected).toBe(false);
      expect(MockWebSocket.instances).toHaveLength(0);
    });

    it('shows error status for invalid URL', () => {
      const { result } = renderHook(() => useWebSocketBase({ wsUrl: 'invalid-url' }));

      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Invalid WebSocket URL protocol (must be ws:// or wss://)');
    });
  });

  describe('connection lifecycle', () => {
    it('transitions to connected on open', () => {
      const onConnect = jest.fn();
      const { result } = renderHook(() =>
        useWebSocketBase({ wsUrl: 'wss://test.com/ws', onConnect }),
      );

      expect(result.current.status).toBe('connecting');

      act(() => {
        getLatestWs().simulateOpen();
      });

      expect(result.current.status).toBe('connected');
      expect(result.current.isConnected).toBe(true);
      expect(onConnect).toHaveBeenCalledTimes(1);
    });

    it('sends subscribe message on connect', () => {
      const subscribeMessage = { type: 'subscribe', channel: 'test' };
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws', subscribeMessage }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      const ws = getLatestWs();
      expect(ws.sentMessages).toHaveLength(1);
      expect(JSON.parse(ws.sentMessages[0])).toEqual(subscribeMessage);
    });

    it('calls onDisconnect when connection closes', () => {
      const onDisconnect = jest.fn();
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws', onDisconnect }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      act(() => {
        getLatestWs().simulateClose(1000);
      });

      expect(onDisconnect).toHaveBeenCalledTimes(1);
    });

    it('calls onError when WebSocket errors', () => {
      const onError = jest.fn();
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws', onError }));

      act(() => {
        getLatestWs().simulateError();
      });

      expect(onError).toHaveBeenCalledWith('WebSocket connection error');
    });
  });

  describe('message handling', () => {
    it('calls onEvent with parsed message', () => {
      const onEvent = jest.fn();
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws', onEvent }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'test', data: 'hello' });
      });

      expect(onEvent).toHaveBeenCalledWith({ type: 'test', data: 'hello' });
    });

    it('deduplicates messages with same seq', () => {
      const onEvent = jest.fn();
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws', onEvent }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'test', seq: 1 });
        getLatestWs().simulateMessage({ type: 'test', seq: 1 }); // Duplicate
        getLatestWs().simulateMessage({ type: 'test', seq: 2 }); // New
      });

      expect(onEvent).toHaveBeenCalledTimes(2);
    });
  });

  describe('send', () => {
    it('sends message when connected', () => {
      const { result } = renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws' }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      act(() => {
        result.current.send({ type: 'ping' });
      });

      const ws = getLatestWs();
      expect(JSON.parse(ws.sentMessages[ws.sentMessages.length - 1])).toEqual({ type: 'ping' });
    });

    it('does not send when disconnected', () => {
      const { result } = renderHook(() =>
        useWebSocketBase({ wsUrl: 'wss://test.com/ws', enabled: false }),
      );

      act(() => {
        result.current.send({ type: 'ping' });
      });

      // No WebSocket created when disabled
      expect(MockWebSocket.instances).toHaveLength(0);
    });
  });

  describe('manual controls', () => {
    it('disconnect closes the connection', () => {
      const { result } = renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws' }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      expect(result.current.isConnected).toBe(true);

      act(() => {
        result.current.disconnect();
      });

      expect(result.current.status).toBe('disconnected');
    });

    it('reconnect resets attempt counter and triggers connection', () => {
      const { result } = renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws' }));

      // Simulate some failed attempts
      act(() => {
        getLatestWs().simulateClose(1006);
      });

      // Advance time for reconnect
      act(() => {
        jest.advanceTimersByTime(2000);
      });

      // Now manually reconnect
      act(() => {
        result.current.reconnect();
      });

      expect(result.current.reconnectAttempt).toBe(0);
      expect(result.current.error).toBeNull();
    });
  });

  describe('reconnection', () => {
    it('schedules reconnect on abnormal close', () => {
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws' }));

      const initialWsCount = MockWebSocket.instances.length;

      act(() => {
        getLatestWs().simulateOpen();
      });

      act(() => {
        getLatestWs().simulateClose(1006, 'Abnormal closure');
      });

      // Advance past reconnect delay
      act(() => {
        jest.advanceTimersByTime(2000);
      });

      // Should have created a new WebSocket
      expect(MockWebSocket.instances.length).toBeGreaterThan(initialWsCount);
    });

    it('does not reconnect on normal close (code 1000)', () => {
      const { result } = renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws' }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      const wsCountAfterConnect = MockWebSocket.instances.length;

      act(() => {
        getLatestWs().simulateClose(1000, 'Normal closure');
      });

      // Advance time
      act(() => {
        jest.advanceTimersByTime(5000);
      });

      expect(result.current.status).toBe('disconnected');
      // Should not create new WebSocket
      expect(MockWebSocket.instances.length).toBe(wsCountAfterConnect);
    });

    it('does not reconnect when autoReconnect is false', () => {
      renderHook(() => useWebSocketBase({ wsUrl: 'wss://test.com/ws', autoReconnect: false }));

      const initialWsCount = MockWebSocket.instances.length;

      act(() => {
        getLatestWs().simulateOpen();
      });

      act(() => {
        getLatestWs().simulateClose(1006);
      });

      // Advance time
      act(() => {
        jest.advanceTimersByTime(10000);
      });

      expect(MockWebSocket.instances.length).toBe(initialWsCount);
    });
  });

  describe('constants', () => {
    it('exports MAX_RECONNECT_ATTEMPTS', () => {
      expect(MAX_RECONNECT_ATTEMPTS).toBe(15);
    });

    it('exports MAX_RECONNECT_DELAY_MS', () => {
      expect(MAX_RECONNECT_DELAY_MS).toBe(30000);
    });
  });
});
