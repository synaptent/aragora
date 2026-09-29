import { render, screen, waitFor } from '@testing-library/react';
import { LiveDebatePanel } from '../LiveDebatePanel';

const mockFetch = jest.fn();
global.fetch = mockFetch as typeof fetch;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = jest.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

describe('LiveDebatePanel', () => {
  const originalSetInterval = window.setInterval;

  beforeEach(() => {
    jest.clearAllMocks();
    MockWebSocket.instances = [];
    mockFetch.mockReset();
    (global as typeof globalThis & { WebSocket: typeof WebSocket }).WebSocket =
      MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    window.setInterval = originalSetInterval;
  });

  it('ignores invalid debate ids from recent events before opening a socket', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          events: [
            {
              event_type: 'proposal',
              timestamp: new Date().toISOString(),
              data: { task: 'bad debate id' },
              debate_id: '../escape',
              pipeline_id: null,
              agent_name: 'agent-1',
              round_number: 1,
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          active: true,
          recent_activity_window_seconds: 120,
          recent_event_count: 1,
        }),
      });

    render(
      <LiveDebatePanel apiBase="https://api.example.test" wsUrl="wss://api.example.test/ws" />,
    );

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    expect(MockWebSocket.instances).toHaveLength(0);
    expect(screen.getByRole('link', { name: /open spectator view/i })).toHaveAttribute(
      'href',
      '/spectate',
    );
  });

  it('uses the slower refresh cadence for the live preview poll loop', () => {
    const setIntervalSpy = jest.spyOn(window, 'setInterval');
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ events: [] }) });

    render(
      <LiveDebatePanel apiBase="https://api.example.test" wsUrl="wss://api.example.test/ws" />,
    );

    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 12000);
    setIntervalSpy.mockRestore();
  });
});
