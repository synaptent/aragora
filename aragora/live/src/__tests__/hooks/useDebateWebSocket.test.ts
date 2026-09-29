import { renderHook, act, waitFor } from '@testing-library/react';
import { useDebateWebSocket } from '@/hooks/useDebateWebSocket';

// Create a mock WebSocket class with proper static constants
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
  onerror: (() => void) | null = null;
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
    if (this.onclose) this.onclose({ code, reason, wasClean: true });
  }

  // Test helpers
  simulateOpen() {
    this.readyState = 1; // WebSocket.OPEN
    if (this.onopen) this.onopen();
  }

  simulateMessage(data: object) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }

  simulateError() {
    if (this.onerror) this.onerror();
  }

  simulateClose(code = 1000, reason = '') {
    this.readyState = 3; // WebSocket.CLOSED
    if (this.onclose) this.onclose({ code, reason, wasClean: code === 1000 });
  }
}

// Store original WebSocket
const originalWebSocket = global.WebSocket;
const originalFetch = global.fetch;
const mockFetch = jest.fn();

describe('useDebateWebSocket', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    localStorage.clear();
    MockWebSocket.instances = [];
    mockFetch.mockReset();
    // Replace global WebSocket with mock, including static constants
    const MockWSWithStatics = MockWebSocket as unknown as typeof WebSocket;
    Object.defineProperty(MockWSWithStatics, 'CONNECTING', { value: 0, writable: true });
    Object.defineProperty(MockWSWithStatics, 'OPEN', { value: 1, writable: true });
    Object.defineProperty(MockWSWithStatics, 'CLOSING', { value: 2, writable: true });
    Object.defineProperty(MockWSWithStatics, 'CLOSED', { value: 3, writable: true });
    (global as { WebSocket: unknown }).WebSocket = MockWSWithStatics;
    (global as { fetch: unknown }).fetch = mockFetch as unknown as typeof fetch;
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
    (global as { fetch: unknown }).fetch = originalFetch as unknown as typeof fetch;
  });

  const getLatestWs = () => MockWebSocket.instances[MockWebSocket.instances.length - 1];

  describe('initial state', () => {
    it('should start with connecting status', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      expect(result.current.status).toBe('connecting');
      expect(result.current.error).toBeNull();
      expect(result.current.isConnected).toBe(false);
      expect(result.current.task).toBe('');
      expect(result.current.agents).toEqual([]);
      expect(result.current.messages).toEqual([]);
      expect(result.current.hasCitations).toBe(false);
    });

    it('should not create WebSocket when disabled', () => {
      renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1', enabled: false }));

      expect(MockWebSocket.instances.length).toBe(0);
    });
  });

  describe('connection lifecycle', () => {
    it('should connect to WebSocket with correct URL', () => {
      renderHook(() =>
        useDebateWebSocket({ debateId: 'test-debate-1', wsUrl: 'wss://custom.ws.url/ws' }),
      );

      expect(getLatestWs().url).toBe('wss://custom.ws.url/ws');
    });

    it('uses the selected runtime backend when wsUrl is omitted', () => {
      localStorage.setItem('aragora-backend', 'production');

      renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      expect(getLatestWs().url).toBe('wss://api.aragora.ai/ws');
    });

    it('should set status to streaming on open', async () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      await waitFor(() => {
        expect(result.current.status).toBe('streaming');
        expect(result.current.isConnected).toBe(true);
      });
    });

    it('should subscribe to debate on open', () => {
      renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      // Get the WebSocket instance before simulating open
      const ws = getLatestWs();

      act(() => {
        ws.simulateOpen();
      });

      // Check if subscribe message was sent
      expect(ws.sentMessages.length).toBe(1);
      expect(JSON.parse(ws.sentMessages[0])).toEqual({
        type: 'subscribe',
        debate_id: 'test-debate-1',
      });
    });

    it('should attempt reconnection on WebSocket error + close', () => {
      // The hook's onerror doesn't set error status - it lets onclose handle it
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateError();
        // Error is followed by close with non-1000 code (abnormal closure)
        getLatestWs().simulateClose(1006, 'Connection lost');
      });

      // Abnormal closure triggers reconnection
      expect(result.current.status).toBe('connecting');
      expect(result.current.error).toContain('Connection lost');
    });

    it('should set status to complete on close when streaming', async () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
      });

      await waitFor(() => {
        expect(result.current.status).toBe('streaming');
      });

      act(() => {
        getLatestWs().simulateClose();
      });

      await waitFor(() => {
        expect(result.current.status).toBe('complete');
      });
    });

    it('should clean up WebSocket on unmount', () => {
      const { unmount } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      const ws = getLatestWs();
      act(() => {
        ws.simulateOpen();
      });

      unmount();

      expect(ws.readyState).toBe(MockWebSocket.CLOSED);
    });
  });

  describe('debate events', () => {
    it('should scope sync events using top-level debate_id and payload id', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'sync',
          debate_id: 'test-debate-1',
          data: { id: 'test-debate-1', task: 'Scoped sync task', agents: ['Agent A', 'Agent B'] },
        });
      });

      expect(result.current.task).toBe('Scoped sync task');
      expect(result.current.agents).toEqual(['Agent A', 'Agent B']);
    });

    it('should handle debate_start event', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'debate_start',
          data: { task: 'Should AI be regulated?', agents: ['Agent A', 'Agent B'] },
        });
      });

      expect(result.current.task).toBe('Should AI be regulated?');
      expect(result.current.agents).toEqual(['Agent A', 'Agent B']);
    });

    it('should handle debate_end event', async () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'debate_end' });
      });

      await waitFor(() => {
        expect(result.current.status).toBe('complete');
      });
    });
  });

  describe('agent messages', () => {
    it('should handle debate_message event', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'debate_message',
          agent: 'Agent A',
          data: { content: 'This is my argument', role: 'proponent' },
          round: 1,
          timestamp: 1234567890,
        });
      });

      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0]).toMatchObject({
        agent: 'Agent A',
        content: 'This is my argument',
        role: 'proponent',
        round: 1,
      });
      expect(result.current.agents).toContain('Agent A');
    });

    it('should deduplicate messages', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      const message = {
        type: 'debate_message',
        agent: 'Agent A',
        data: { content: 'Same message' },
        timestamp: 1234567890,
      };

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage(message);
        getLatestWs().simulateMessage(message);
        getLatestWs().simulateMessage(message);
      });

      // Should only have one message
      expect(result.current.messages.length).toBe(1);
    });

    it('should ignore messages from other debates', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'debate_message',
          loop_id: 'other-debate',
          agent: 'Agent X',
          data: { content: 'Should be ignored' },
        });
      });

      expect(result.current.messages.length).toBe(0);
    });
  });

  describe('token streaming', () => {
    it('should handle token_start event', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'token_start', agent: 'Agent A' });
      });

      expect(result.current.streamingMessages.has('Agent A')).toBe(true);
      expect(result.current.streamingMessages.get('Agent A')?.content).toBe('');
      expect(result.current.streamingMessages.get('Agent A')?.isComplete).toBe(false);
    });

    it('should handle token_delta events', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'token_start', agent: 'Agent A' });
        getLatestWs().simulateMessage({
          type: 'token_delta',
          agent: 'Agent A',
          data: { token: 'Hello ' },
        });
        getLatestWs().simulateMessage({
          type: 'token_delta',
          agent: 'Agent A',
          data: { token: 'world!' },
        });
      });

      expect(result.current.streamingMessages.get('Agent A')?.content).toBe('Hello world!');
    });

    it('should handle token_end event and convert to message', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'token_start', agent: 'Agent A' });
        getLatestWs().simulateMessage({
          type: 'token_delta',
          agent: 'Agent A',
          data: { token: 'Complete message' },
        });
        getLatestWs().simulateMessage({ type: 'token_end', agent: 'Agent A' });
      });

      // Streaming should be cleared
      expect(result.current.streamingMessages.has('Agent A')).toBe(false);
      // Message should be added
      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0].content).toBe('Complete message');
    });
  });

  describe('special events', () => {
    it('should handle critique event', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'critique',
          agent: 'Critic',
          data: { target: 'Agent A', issues: ['Logical fallacy', 'Missing evidence'] },
        });
      });

      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0].role).toBe('critic');
      expect(result.current.messages[0].content).toContain('CRITIQUE');
      expect(result.current.messages[0].content).toContain('Agent A');
    });

    it('should handle consensus event', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'consensus',
          data: { reached: true, confidence: 0.85 },
        });
      });

      // Consensus events are tracked as stream events (messages only added if synthesis present)
      expect(result.current.streamEvents.length).toBe(1);
      expect(result.current.streamEvents[0].type).toBe('consensus');
      expect(result.current.streamEvents[0].data.reached).toBe(true);
      expect(result.current.streamEvents[0].data.confidence).toBe(0.85);
    });

    it('should handle grounded_verdict event and set hasCitations', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({
          type: 'grounded_verdict',
          data: { citations: ['source1', 'source2'] },
        });
      });

      expect(result.current.hasCitations).toBe(true);
      expect(result.current.streamEvents.length).toBe(1);
    });
  });

  describe('user actions', () => {
    it('should send vote when connected', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      const ws = getLatestWs();

      act(() => {
        ws.simulateOpen();
        // Send vote in the same act to ensure state is updated
        result.current.sendVote('Agent A', 8);
      });

      // First message is subscribe, second is vote
      expect(ws.sentMessages.length).toBe(2);
      const voteMessage = JSON.parse(ws.sentMessages[1]);
      expect(voteMessage).toEqual({
        type: 'user_vote',
        debate_id: 'test-debate-1',
        data: { choice: 'Agent A', intensity: 8 },
      });
    });

    it('should use default intensity when not provided', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      const ws = getLatestWs();

      act(() => {
        ws.simulateOpen();
        result.current.sendVote('Agent A');
      });

      expect(ws.sentMessages.length).toBe(2);
      const voteMessage = JSON.parse(ws.sentMessages[1]);
      expect(voteMessage.data.intensity).toBe(5);
    });

    it('should send suggestion when connected', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      const ws = getLatestWs();

      act(() => {
        ws.simulateOpen();
        result.current.sendSuggestion('Consider the environment');
      });

      expect(ws.sentMessages.length).toBe(2);
      const suggestionMessage = JSON.parse(ws.sentMessages[1]);
      expect(suggestionMessage).toEqual({
        type: 'user_suggestion',
        debate_id: 'test-debate-1',
        data: { suggestion: 'Consider the environment' },
      });
    });

    it('should not send when WebSocket is not open', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      const ws = getLatestWs();

      // Don't open the WebSocket
      act(() => {
        result.current.sendVote('Agent A');
        result.current.sendSuggestion('Test');
      });

      // No messages should be sent when not connected
      expect(ws.sentMessages.length).toBe(0);
    });
  });

  describe('callbacks', () => {
    it('should call ack callback on ack event', () => {
      const ackCallback = jest.fn();
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        result.current.registerAckCallback(ackCallback);
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'ack', data: { message_type: 'user_vote' } });
      });

      expect(ackCallback).toHaveBeenCalledWith('user_vote');
    });

    it('should call error callback on error event', () => {
      const errorCallback = jest.fn();
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        result.current.registerErrorCallback(errorCallback);
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'error', data: { message: 'Something went wrong' } });
      });

      expect(errorCallback).toHaveBeenCalledWith('Something went wrong');
    });

    it('should unregister callbacks when cleanup is called', () => {
      const ackCallback = jest.fn();
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      let unregister: () => void;
      act(() => {
        unregister = result.current.registerAckCallback(ackCallback);
      });

      act(() => {
        unregister();
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'ack', data: { message_type: 'user_vote' } });
      });

      expect(ackCallback).not.toHaveBeenCalled();
    });
  });

  describe('stream events buffer', () => {
    it('should limit stream events to MAX_STREAM_EVENTS', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        // Send more than 500 events
        for (let i = 0; i < 550; i++) {
          getLatestWs().simulateMessage({
            type: 'audience_metrics',
            data: { count: i },
            timestamp: i,
          });
        }
      });

      // Should be capped at 500
      expect(result.current.streamEvents.length).toBeLessThanOrEqual(500);
    });
  });

  describe('orphan stream cleanup', () => {
    it('should timeout stale streaming messages', async () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'token_start', agent: 'Agent A' });
        getLatestWs().simulateMessage({
          type: 'token_delta',
          agent: 'Agent A',
          data: { token: 'Incomplete' },
        });
      });

      expect(result.current.streamingMessages.has('Agent A')).toBe(true);

      // Advance time past the timeout (300 seconds = 5 minutes)
      // Hook uses 300s to exceed backend agent timeout of 240s
      act(() => {
        jest.advanceTimersByTime(305000);
      });

      // Streaming should be cleared and message added with timeout indicator
      expect(result.current.streamingMessages.has('Agent A')).toBe(false);
      const timedOutMessage = result.current.messages.find((m) =>
        m.content.includes('[stream timed out]'),
      );
      expect(timedOutMessage).toBeDefined();
    });
  });

  describe('cleanup on status change', () => {
    it('should clear stream events when debate completes', () => {
      const { result } = renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        getLatestWs().simulateMessage({ type: 'audience_metrics', data: { count: 1 } });
      });

      expect(result.current.streamEvents.length).toBe(1);

      act(() => {
        getLatestWs().simulateMessage({ type: 'debate_end' });
      });

      expect(result.current.streamEvents.length).toBe(0);
    });
  });

  describe('runtime backend fallback', () => {
    it('uses the selected runtime backend for HTTP status fallback', async () => {
      localStorage.setItem('aragora-backend', 'production');
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ status: 'running' }),
      } as Response);

      renderHook(() => useDebateWebSocket({ debateId: 'test-debate-1' }));

      act(() => {
        getLatestWs().simulateOpen();
        jest.advanceTimersByTime(180000);
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('https://api.aragora.ai/api/debates/test-debate-1');
      });
    });
  });
});
