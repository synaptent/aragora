import { renderHook, act } from '@testing-library/react';
import { useOracleWebSocket } from '@/hooks/useOracleWebSocket';

jest.mock('@/config', () => ({ WS_URL: 'wss://test.com/ws' }));

const mockAudio = {
  appendChunk: jest.fn(),
  endSegment: jest.fn(),
  stop: jest.fn(),
  pause: jest.fn(),
  resume: jest.fn(),
  isPlaying: jest.fn(() => false),
  isPaused: jest.fn(() => false),
};

jest.mock('../../hooks/useStreamingAudio', () => ({ useStreamingAudio: () => mockAudio }));

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  binaryType = 'blob';
  url: string;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function latestSocket(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

beforeAll(() => {
  (global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;
});

afterAll(() => {
  jest.useRealTimers();
});

beforeEach(() => {
  jest.useFakeTimers();
  MockWebSocket.instances = [];
  jest.clearAllMocks();
});

describe('useOracleWebSocket metrics', () => {
  it('records TTFT on first token', () => {
    const { result } = renderHook(() => useOracleWebSocket());
    const ws = latestSocket();

    act(() => {
      ws.simulateOpen();
      result.current.ask('What is the future of AI?', 'consult');
      ws.simulateMessage({ type: 'reflex_start' });
      ws.simulateMessage({ type: 'token', text: 'A', phase: 'reflex' });
      ws.simulateMessage({ type: 'token', text: 'B', phase: 'reflex' });
    });

    expect(result.current.timeToFirstTokenMs).not.toBeNull();
    expect(result.current.timeToFirstTokenMs).toBeGreaterThanOrEqual(0);
  });

  it('records stream duration when synthesis arrives', () => {
    const { result } = renderHook(() => useOracleWebSocket());
    const ws = latestSocket();

    act(() => {
      ws.simulateOpen();
      result.current.ask('Give me three strategic options', 'divine');
      ws.simulateMessage({ type: 'reflex_start' });
      ws.simulateMessage({ type: 'token', text: 'X', phase: 'reflex' });
      ws.simulateMessage({ type: 'synthesis', text: 'Final synthesis' });
    });

    expect(result.current.timeToFirstTokenMs).not.toBeNull();
    expect(result.current.streamDurationMs).not.toBeNull();
    expect(result.current.streamDurationMs).toBeGreaterThanOrEqual(
      result.current.timeToFirstTokenMs || 0,
    );
  });

  it('resets previous latency metrics on a new ask', () => {
    const { result } = renderHook(() => useOracleWebSocket());
    const ws = latestSocket();

    act(() => {
      ws.simulateOpen();
      result.current.ask('first', 'consult');
      ws.simulateMessage({ type: 'token', text: '1', phase: 'reflex' });
      ws.simulateMessage({ type: 'synthesis', text: 'done' });
    });

    expect(result.current.timeToFirstTokenMs).not.toBeNull();
    expect(result.current.streamDurationMs).not.toBeNull();

    act(() => {
      result.current.ask('second', 'consult');
    });

    expect(result.current.timeToFirstTokenMs).toBeNull();
    expect(result.current.streamDurationMs).toBeNull();
  });

  it('marks stream stalled when first token timeout elapses', () => {
    const { result } = renderHook(() => useOracleWebSocket());
    const ws = latestSocket();

    act(() => {
      ws.simulateOpen();
      result.current.ask('slow stream', 'consult');
      ws.simulateMessage({ type: 'reflex_start' });
    });

    expect(result.current.streamStalled).toBe(false);
    expect(result.current.stallReason).toBeNull();

    act(() => {
      jest.advanceTimersByTime(15001);
    });

    expect(result.current.streamStalled).toBe(true);
    expect(result.current.stallReason).toBe('waiting_first_token');
  });

  it('marks stream stalled on inactivity after first token and clears on resumed activity', () => {
    const { result } = renderHook(() => useOracleWebSocket());
    const ws = latestSocket();

    act(() => {
      ws.simulateOpen();
      result.current.ask('watch for stalls', 'consult');
      ws.simulateMessage({ type: 'reflex_start' });
      ws.simulateMessage({ type: 'token', text: 'a', phase: 'reflex' });
    });

    expect(result.current.streamStalled).toBe(false);
    expect(result.current.stallReason).toBeNull();

    act(() => {
      jest.advanceTimersByTime(20001);
    });

    expect(result.current.streamStalled).toBe(true);
    expect(result.current.stallReason).toBe('stream_inactive');

    act(() => {
      ws.simulateMessage({ type: 'token', text: 'b', phase: 'reflex' });
    });

    expect(result.current.streamStalled).toBe(false);
    expect(result.current.stallReason).toBeNull();
  });
});
