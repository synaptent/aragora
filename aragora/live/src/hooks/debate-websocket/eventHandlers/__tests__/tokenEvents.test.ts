/**
 * Tests for token streaming and reasoning event handlers
 *
 * Tests cover:
 * - handleTokenStartEvent initializes stream with reasoning fields
 * - handleTokenDeltaEvent creates fallback with reasoning fields
 * - handleAgentThinkingEvent appends reasoning steps
 * - handleAgentEvidenceEvent appends evidence sources
 * - handleAgentConfidenceEvent updates confidence
 * - tokenHandlers registry includes all handlers
 */

import {
  handleTokenStartEvent,
  handleTokenDeltaEvent,
  handleTokenEndEvent,
  handleAgentThinkingEvent,
  handleAgentReasoningEvent,
  handleAgentEvidenceEvent,
  handleAgentConfidenceEvent,
  tokenHandlers,
} from '../tokenEvents';
import type { EventHandlerContext, ParsedEventData } from '../types';
import type { StreamingMessage } from '../../types';

// Create a minimal mock context
function createMockContext(overrides: Partial<EventHandlerContext> = {}): EventHandlerContext {
  const streamingMessages = new Map<string, StreamingMessage>();

  return {
    debateId: 'test-debate',
    setTask: jest.fn(),
    setAgents: jest.fn(),
    setDebateMode: jest.fn(),
    setSettlementMetadata: jest.fn(),
    setStatus: jest.fn(),
    setError: jest.fn(),
    setErrorDetails: jest.fn(),
    setHasCitations: jest.fn(),
    setHasReceivedDebateStart: jest.fn(),
    setStreamingMessages: jest.fn((updater) => {
      if (typeof updater === 'function') {
        const result = updater(streamingMessages);
        // Apply the update to our local map for subsequent calls
        streamingMessages.clear();
        for (const [k, v] of result.entries()) {
          streamingMessages.set(k, v);
        }
      }
    }),
    addMessageIfNew: jest.fn(() => true),
    addStreamEvent: jest.fn(),
    clearDebateStartTimeout: jest.fn(),
    errorCallbackRef: { current: null },
    ackCallbackRef: { current: null },
    seenMessagesRef: { current: new Set() },
    lastSeqRef: { current: 0 },
    ...overrides,
  };
}

describe('tokenEvents handlers', () => {
  describe('handleTokenStartEvent', () => {
    it('initializes streaming message with reasoning fields', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = { type: 'token_start', agent: 'claude', task_id: '' };

      handleTokenStartEvent(data, ctx);

      expect(ctx.setStreamingMessages).toHaveBeenCalled();
      // Verify the updater was called with correct shape
      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(new Map());
      const msg = result.get('claude');

      expect(msg).toBeDefined();
      expect(msg.agent).toBe('claude');
      expect(msg.content).toBe('');
      expect(msg.reasoning).toEqual([]);
      expect(msg.evidence).toEqual([]);
      expect(msg.confidence).toBeNull();
    });

    it('uses composite key with taskId', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = { type: 'token_start', agent: 'claude', task_id: 'task-42' };

      handleTokenStartEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(new Map());
      expect(result.has('claude:task-42')).toBe(true);
    });
  });

  describe('handleTokenDeltaEvent', () => {
    it('creates fallback stream with reasoning fields when no prior token_start', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = {
        type: 'token_delta',
        agent: 'gpt-4',
        task_id: '',
        data: { token: 'Hello' },
      };

      handleTokenDeltaEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(new Map());
      const msg = result.get('gpt-4');

      expect(msg).toBeDefined();
      expect(msg.content).toBe('Hello');
      expect(msg.reasoning).toEqual([]);
      expect(msg.evidence).toEqual([]);
      expect(msg.confidence).toBeNull();
    });
  });

  describe('handleAgentThinkingEvent', () => {
    it('appends reasoning step to active streaming message', () => {
      const ctx = createMockContext();
      // Pre-populate a streaming message
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('claude', {
        agent: 'claude',
        taskId: '',
        content: 'Partial response...',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });

      // Override setStreamingMessages to capture updates against existing map
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') {
          updater(existingMap);
        }
      });

      const data: ParsedEventData = {
        type: 'agent_thinking',
        agent: 'claude',
        data: { thinking: 'Considering counterargument', step: 2 },
        timestamp: 1234567890,
      };

      handleAgentThinkingEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(existingMap);
      const msg = result.get('claude');

      expect(msg.reasoning).toHaveLength(1);
      expect(msg.reasoning[0].thinking).toBe('Considering counterargument');
      expect(msg.reasoning[0].step).toBe(2);
      expect(msg.reasoning[0].timestamp).toBeDefined();
    });

    it('adds stream event for thinking', () => {
      const ctx = createMockContext();
      // Pre-populate a streaming message
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('claude', {
        agent: 'claude',
        taskId: '',
        content: '',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') updater(existingMap);
      });

      const data: ParsedEventData = {
        type: 'agent_thinking',
        agent: 'claude',
        data: { thinking: 'Analysis step' },
        timestamp: 1234567890,
      };

      handleAgentThinkingEvent(data, ctx);

      expect(ctx.addStreamEvent).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'agent_thinking', agent: 'claude' }),
      );
    });

    it('ignores events without agent', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = { type: 'agent_thinking', data: { thinking: 'No agent' } };

      handleAgentThinkingEvent(data, ctx);

      expect(ctx.setStreamingMessages).not.toHaveBeenCalled();
    });

    it('ignores events without thinking content', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = {
        type: 'agent_thinking',
        agent: 'claude',
        data: { thinking: '' },
      };

      handleAgentThinkingEvent(data, ctx);

      expect(ctx.setStreamingMessages).not.toHaveBeenCalled();
    });
  });

  describe('handleAgentEvidenceEvent', () => {
    it('appends evidence sources to streaming message', () => {
      const ctx = createMockContext();
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('gpt-4', {
        agent: 'gpt-4',
        taskId: '',
        content: 'Response...',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') updater(existingMap);
      });

      const data: ParsedEventData = {
        type: 'agent_evidence',
        agent: 'gpt-4',
        data: {
          sources: [
            { title: 'Paper A', url: 'https://example.com/a', relevance: 0.9 },
            { title: 'Paper B', relevance: 0.7 },
          ],
        },
      };

      handleAgentEvidenceEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(existingMap);
      const msg = result.get('gpt-4');

      expect(msg.evidence).toHaveLength(2);
      expect(msg.evidence[0].title).toBe('Paper A');
      expect(msg.evidence[1].relevance).toBe(0.7);
    });

    it('ignores events with empty sources', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = {
        type: 'agent_evidence',
        agent: 'claude',
        data: { sources: [] },
      };

      handleAgentEvidenceEvent(data, ctx);

      expect(ctx.setStreamingMessages).not.toHaveBeenCalled();
    });
  });

  describe('handleAgentConfidenceEvent', () => {
    it('updates confidence on streaming message', () => {
      const ctx = createMockContext();
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('claude', {
        agent: 'claude',
        taskId: '',
        content: 'Response...',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') updater(existingMap);
      });

      const data: ParsedEventData = {
        type: 'agent_confidence',
        agent: 'claude',
        data: { confidence: 0.85 },
      };

      handleAgentConfidenceEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(existingMap);
      const msg = result.get('claude');

      expect(msg.confidence).toBe(0.85);
    });

    it('ignores events with null confidence', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = { type: 'agent_confidence', agent: 'claude', data: {} };

      handleAgentConfidenceEvent(data, ctx);

      expect(ctx.setStreamingMessages).not.toHaveBeenCalled();
    });
  });

  describe('tokenHandlers registry', () => {
    it('includes all token streaming handlers', () => {
      expect(tokenHandlers.token_start).toBe(handleTokenStartEvent);
      expect(tokenHandlers.token_delta).toBe(handleTokenDeltaEvent);
      expect(tokenHandlers.token_end).toBe(handleTokenEndEvent);
    });

    it('includes all reasoning handlers', () => {
      expect(tokenHandlers.agent_thinking).toBe(handleAgentThinkingEvent);
      expect(tokenHandlers.agent_reasoning).toBe(handleAgentReasoningEvent);
      expect(tokenHandlers.agent_evidence).toBe(handleAgentEvidenceEvent);
      expect(tokenHandlers.agent_confidence).toBe(handleAgentConfidenceEvent);
    });

    it('has exactly 7 handlers registered', () => {
      expect(Object.keys(tokenHandlers)).toHaveLength(7);
    });
  });

  describe('handleAgentReasoningEvent', () => {
    it('updates reasoning phase on streaming message', () => {
      const ctx = createMockContext();
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('claude', {
        agent: 'claude',
        taskId: '',
        content: 'Response...',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') updater(existingMap);
      });

      const data: ParsedEventData = {
        type: 'agent_reasoning',
        agent: 'claude',
        data: { phase: 'FORMING ARGUMENT' },
      };

      handleAgentReasoningEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(existingMap);
      const msg = result.get('claude');

      expect(msg.reasoningPhase).toBe('FORMING ARGUMENT');
    });

    it('accepts reasoning_phase field name', () => {
      const ctx = createMockContext();
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('gpt-4', {
        agent: 'gpt-4',
        taskId: '',
        content: '',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') updater(existingMap);
      });

      const data: ParsedEventData = {
        type: 'agent_reasoning',
        agent: 'gpt-4',
        data: { reasoning_phase: 'CRITIQUING' },
      };

      handleAgentReasoningEvent(data, ctx);

      const updater = (ctx.setStreamingMessages as jest.Mock).mock.calls[0][0];
      const result = updater(existingMap);
      const msg = result.get('gpt-4');

      expect(msg.reasoningPhase).toBe('CRITIQUING');
    });

    it('adds stream event for reasoning phase', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = {
        type: 'agent_reasoning',
        agent: 'claude',
        data: { phase: 'ANALYZING' },
        timestamp: 1234567890,
      };

      handleAgentReasoningEvent(data, ctx);

      expect(ctx.addStreamEvent).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'agent_reasoning', agent: 'claude' }),
      );
    });

    it('ignores events without agent', () => {
      const ctx = createMockContext();
      const data: ParsedEventData = { type: 'agent_reasoning', data: { phase: 'ANALYZING' } };

      handleAgentReasoningEvent(data, ctx);

      expect(ctx.setStreamingMessages).not.toHaveBeenCalled();
    });
  });

  describe('handleTokenEndEvent', () => {
    it('propagates confidence and reasoning phase to transcript message', () => {
      const ctx = createMockContext();
      const existingMap = new Map<string, StreamingMessage>();
      existingMap.set('claude', {
        agent: 'claude',
        taskId: '',
        content: 'Final response text',
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: 1,
        pendingTokens: new Map(),
        reasoning: [{ thinking: 'Step 1 analysis', timestamp: Date.now(), step: 1 }],
        evidence: [],
        confidence: 0.92,
        reasoningPhase: 'FORMING ARGUMENT',
      });
      ctx.setStreamingMessages = jest.fn((updater) => {
        if (typeof updater === 'function') updater(existingMap);
      });

      const data: ParsedEventData = { type: 'token_end', agent: 'claude', task_id: '' };

      handleTokenEndEvent(data, ctx);

      expect(ctx.addMessageIfNew).toHaveBeenCalledWith(
        expect.objectContaining({
          agent: 'claude',
          content: 'Final response text',
          confidence_score: 0.92,
          reasoning_phase: 'FORMING ARGUMENT',
          thinking: 'Step 1 analysis',
        }),
      );
    });
  });
});
