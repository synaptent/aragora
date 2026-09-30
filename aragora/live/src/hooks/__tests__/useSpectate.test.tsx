import { act, renderHook, waitFor } from '@testing-library/react';
import { useSpectate } from '../useSpectate';

jest.mock('@/config', () => ({ API_BASE_URL: 'https://api.example.com' }));

type Listener = (event: { data: string }) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close() {
    this.closed = true;
  }

  simulateOpen() {
    this.onopen?.();
  }

  simulateError() {
    this.onerror?.();
  }

  emit(type: string, payload: unknown) {
    const listeners = this.listeners.get(type) ?? [];
    const event = { data: JSON.stringify(payload) };
    listeners.forEach((listener) => listener(event));
  }
}

function createStatusPayload() {
  return {
    active: true,
    subscribers: 1,
    buffer_size: 4,
    bridge_state: 'live_debates_available' as const,
    last_event_at: '2026-04-03T11:00:00Z',
    activity_age_seconds: 2,
    recent_activity_window_seconds: 120,
    recent_event_count: 3,
    live_debate_count: 1,
    live_debate_ids: ['debate-1'],
    live_debates: [
      {
        debate_id: 'debate-1',
        recent_event_count: 3,
        last_event_at: '2026-04-03T11:00:00Z',
        event_types: ['proposal'],
      },
    ],
    unattributed_recent_event_count: 0,
  };
}

function createJsonResponse(payload: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) });
}

describe('useSpectate', () => {
  const originalEventSource = global.EventSource;
  const originalFetch = global.fetch;

  beforeAll(() => {
    (global as typeof global & { EventSource: typeof MockEventSource }).EventSource =
      MockEventSource;
  });

  afterAll(() => {
    global.EventSource = originalEventSource;
    global.fetch = originalFetch;
  });

  beforeEach(() => {
    MockEventSource.instances = [];
    global.fetch = jest.fn();
  });

  it('prefers live EventSource delivery when spectate streaming is available', async () => {
    const mockFetch = global.fetch as jest.Mock;
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse(createStatusPayload());
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { result, unmount } = renderHook(() =>
      useSpectate('debate-1', undefined, { pollInterval: 1000, maxEvents: 5 }),
    );

    await waitFor(() => {
      expect(MockEventSource.instances).toHaveLength(1);
    });

    const stream = MockEventSource.instances[0];
    expect(stream.url).toBe(
      'https://api.example.com/api/v1/spectate/stream?count=5&debate_id=debate-1',
    );

    act(() => {
      stream.simulateOpen();
      stream.emit('connected', { mode: 'live' });
      stream.emit('spectate', {
        event_type: 'proposal',
        timestamp: '2026-04-03T11:00:00Z',
        data: { details: 'Ship the live public bridge.' },
        debate_id: 'debate-1',
        pipeline_id: null,
        agent_name: 'claude',
        round_number: 1,
      });
    });

    await waitFor(() => {
      expect(result.current.connected).toBe(true);
      expect(result.current.loaded).toBe(true);
      expect(result.current.events).toHaveLength(1);
    });

    expect(result.current.events[0].event_type).toBe('proposal');
    expect(result.current.events[0].agent_name).toBe('claude');
    expect(
      mockFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/spectate/recent')),
    ).toBe(false);

    unmount();
    expect(stream.closed).toBe(true);
  });

  it('consumes finite snapshot SSE event types without falling back to polling', async () => {
    const mockFetch = global.fetch as jest.Mock;
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse(createStatusPayload());
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { result } = renderHook(() =>
      useSpectate('debate-1', undefined, { pollInterval: 1000, maxEvents: 5 }),
    );

    await waitFor(() => {
      expect(MockEventSource.instances).toHaveLength(1);
    });

    const stream = MockEventSource.instances[0];

    act(() => {
      stream.simulateOpen();
      stream.emit('connected', { mode: 'snapshot' });
      stream.emit('proposal', {
        event_type: 'proposal',
        timestamp: '2026-04-03T11:00:01Z',
        data: { details: 'Snapshot fallback still needs to populate the transcript.' },
        debate_id: 'debate-1',
        pipeline_id: null,
        agent_name: 'judge',
        round_number: 1,
      });
      stream.emit('snapshot_complete', { mode: 'snapshot' });
    });

    await waitFor(() => {
      expect(result.current.connected).toBe(true);
      expect(result.current.loaded).toBe(true);
      expect(result.current.events).toHaveLength(1);
    });

    expect(result.current.events[0].event_type).toBe('proposal');
    expect(result.current.events[0].agent_name).toBe('judge');
    expect(
      mockFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/spectate/recent')),
    ).toBe(false);
  });

  it('falls back to recent-event polling when the SSE stream errors', async () => {
    const mockFetch = global.fetch as jest.Mock;
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse(createStatusPayload());
      }
      if (url.endsWith('/api/v1/spectate/recent?count=4')) {
        return createJsonResponse({
          events: [
            {
              event_type: 'critique',
              timestamp: '2026-04-03T11:00:02Z',
              data: { details: 'Do not fake liveness.' },
              debate_id: 'debate-1',
              pipeline_id: null,
              agent_name: 'gpt4',
              round_number: 1,
            },
          ],
          count: 1,
        });
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { result } = renderHook(() =>
      useSpectate(undefined, undefined, { pollInterval: 1000, maxEvents: 4 }),
    );

    await waitFor(() => {
      expect(MockEventSource.instances).toHaveLength(1);
    });

    act(() => {
      MockEventSource.instances[0].simulateError();
    });

    await waitFor(() => {
      expect(result.current.connected).toBe(true);
      expect(result.current.events).toHaveLength(1);
    });

    expect(result.current.events[0].event_type).toBe('critique');
    expect(result.current.events[0].agent_name).toBe('gpt4');
    expect(
      mockFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/spectate/recent?count=4')),
    ).toBe(true);
  });

  it('resyncs from recent events when the live stream reports overflow', async () => {
    const mockFetch = global.fetch as jest.Mock;
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse(createStatusPayload());
      }
      if (url.endsWith('/api/v1/spectate/recent?count=4')) {
        return createJsonResponse({
          events: [
            {
              event_type: 'consensus',
              timestamp: '2026-04-03T11:00:03Z',
              data: { details: 'Recovered from a stream gap.' },
              debate_id: 'debate-1',
              pipeline_id: null,
              agent_name: 'judge',
              round_number: 2,
            },
          ],
          count: 1,
        });
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { result } = renderHook(() =>
      useSpectate(undefined, undefined, { pollInterval: 1000, maxEvents: 4 }),
    );

    await waitFor(() => {
      expect(MockEventSource.instances).toHaveLength(1);
    });

    const stream = MockEventSource.instances[0];

    act(() => {
      stream.simulateOpen();
      stream.emit('resync_required', { reason: 'queue_overflow', dropped_events: 3 });
    });

    await waitFor(() => {
      expect(result.current.connected).toBe(true);
      expect(result.current.events).toHaveLength(1);
    });

    expect(stream.closed).toBe(true);
    expect(result.current.events[0].event_type).toBe('consensus');
    expect(
      mockFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/spectate/recent?count=4')),
    ).toBe(true);
  });
});
