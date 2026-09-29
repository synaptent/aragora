import {
  handleDebateEndEvent,
  handleDebateStartEvent,
  handleSyncEvent,
  lifecycleHandlers,
} from '../lifecycleEvents';
import type { EventHandlerContext, ParsedEventData } from '../types';

function createMockContext(overrides: Partial<EventHandlerContext> = {}): EventHandlerContext {
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
    setStreamingMessages: jest.fn(),
    addMessageIfNew: jest.fn(() => true),
    addStreamEvent: jest.fn(),
    clearDebateStartTimeout: jest.fn(),
    setConnectionQuality: jest.fn(),
    errorCallbackRef: { current: null },
    ackCallbackRef: { current: null },
    seenMessagesRef: { current: new Set() },
    lastSeqRef: { current: 0 },
    lastActivityRef: { current: Date.now() },
    ...overrides,
  };
}

describe('lifecycleEvents handlers', () => {
  it('captures mode and settlement metadata on debate_start', () => {
    const ctx = createMockContext();
    const data: ParsedEventData = {
      type: 'debate_start',
      data: {
        task: 'Should we ship this?',
        agents: ['claude', 'gpt-5'],
        mode: 'epistemic_hygiene',
        settlement: { status: 'needs_definition', resolver_type: 'human', sla_state: 'pending' },
      },
    };

    handleDebateStartEvent(data, ctx);

    expect(ctx.setTask).toHaveBeenCalledWith('Should we ship this?');
    expect(ctx.setAgents).toHaveBeenCalledWith(['claude', 'gpt-5']);
    expect(ctx.setDebateMode).toHaveBeenCalledWith('epistemic_hygiene');
    expect(ctx.setSettlementMetadata).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'needs_definition', resolver_type: 'human' }),
    );
  });

  it('captures mode and settlement metadata on sync', () => {
    const ctx = createMockContext();
    const data: ParsedEventData = {
      type: 'sync',
      data: {
        task: 'Sync task',
        agents: ['claude'],
        mode: 'epistemic_hygiene',
        settlement: { status: 'pending_human_adjudication', sla_state: 'pending' },
        messages: [],
      },
    };

    handleSyncEvent(data, ctx);

    expect(ctx.setDebateMode).toHaveBeenCalledWith('epistemic_hygiene');
    expect(ctx.setSettlementMetadata).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'pending_human_adjudication' }),
    );
  });

  it('captures mode and settlement metadata from debate_end summary', () => {
    const ctx = createMockContext();
    const data: ParsedEventData = {
      type: 'debate_end',
      data: {
        summary: {
          task: 'Done',
          mode: 'epistemic_hygiene',
          settlement: { status: 'settled_true', sla_state: 'settled' },
        },
      },
    };

    handleDebateEndEvent(data, ctx);

    expect(ctx.setDebateMode).toHaveBeenCalledWith('epistemic_hygiene');
    expect(ctx.setSettlementMetadata).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'settled_true', sla_state: 'settled' }),
    );
  });

  it('registry exposes core lifecycle handlers', () => {
    expect(lifecycleHandlers.debate_start).toBeDefined();
    expect(lifecycleHandlers.debate_end).toBeDefined();
    expect(lifecycleHandlers.sync).toBeDefined();
    expect(lifecycleHandlers.debate_error).toBeDefined();
  });
});
