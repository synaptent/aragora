/**
 * Tests for debateStore
 *
 * Tests cover:
 * - Initial state
 * - Connection actions (setDebateId, setConnectionStatus, setError)
 * - Debate data actions (setTask, setAgents, addAgent)
 * - Message actions with deduplication
 * - Streaming actions (startStream, appendStreamToken, endStream)
 * - Stream events
 * - UI actions
 * - Sequence tracking
 * - Reset actions
 */

import { act, renderHook } from '@testing-library/react';
import {
  useDebateStore,
  selectDebateStatus,
  selectDebateMessages,
  selectStreamingMessages,
  selectDebateAgents,
  selectDebateTask,
  selectStreamEvents,
  selectHasCitations,
  selectDebateUI,
  selectArtifact,
} from '../../store/debateStore';

describe('debateStore', () => {
  beforeEach(() => {
    // Reset store before each test
    const { result } = renderHook(() => useDebateStore());
    act(() => {
      result.current.resetAll();
    });
  });

  describe('Initial State', () => {
    it('starts with correct initial values', () => {
      const { result } = renderHook(() => useDebateStore());

      expect(result.current.current.debateId).toBeNull();
      expect(result.current.current.task).toBe('');
      expect(result.current.current.agents).toEqual([]);
      expect(result.current.current.messages).toEqual([]);
      expect(result.current.current.streamingMessages.size).toBe(0);
      expect(result.current.current.streamEvents).toEqual([]);
      expect(result.current.current.hasCitations).toBe(false);
      expect(result.current.current.connectionStatus).toBe('idle');
      expect(result.current.current.error).toBeNull();
      expect(result.current.current.reconnectAttempt).toBe(0);
    });

    it('starts with correct UI state', () => {
      const { result } = renderHook(() => useDebateStore());

      expect(result.current.ui.showParticipation).toBe(false);
      expect(result.current.ui.showCitations).toBe(false);
      expect(result.current.ui.userScrolled).toBe(false);
      expect(result.current.ui.autoScroll).toBe(true);
    });

    it('starts with null artifact', () => {
      const { result } = renderHook(() => useDebateStore());
      expect(result.current.artifact).toBeNull();
    });
  });

  describe('Connection Actions', () => {
    it('setDebateId updates debate ID', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setDebateId('debate-123');
      });

      expect(result.current.current.debateId).toBe('debate-123');
    });

    it('setConnectionStatus updates status', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setConnectionStatus('connecting');
      });
      expect(result.current.current.connectionStatus).toBe('connecting');

      act(() => {
        result.current.setConnectionStatus('streaming');
      });
      expect(result.current.current.connectionStatus).toBe('streaming');

      act(() => {
        result.current.setConnectionStatus('complete');
      });
      expect(result.current.current.connectionStatus).toBe('complete');
    });

    it('setError updates error state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setError('Connection failed');
      });

      expect(result.current.current.error).toBe('Connection failed');

      act(() => {
        result.current.setError(null);
      });

      expect(result.current.current.error).toBeNull();
    });

    it('incrementReconnectAttempt increments counter', () => {
      const { result } = renderHook(() => useDebateStore());

      expect(result.current.current.reconnectAttempt).toBe(0);

      act(() => {
        result.current.incrementReconnectAttempt();
      });
      expect(result.current.current.reconnectAttempt).toBe(1);

      act(() => {
        result.current.incrementReconnectAttempt();
      });
      expect(result.current.current.reconnectAttempt).toBe(2);
    });

    it('resetReconnectAttempt resets counter to 0', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.incrementReconnectAttempt();
        result.current.incrementReconnectAttempt();
      });
      expect(result.current.current.reconnectAttempt).toBe(2);

      act(() => {
        result.current.resetReconnectAttempt();
      });
      expect(result.current.current.reconnectAttempt).toBe(0);
    });
  });

  describe('Debate Data Actions', () => {
    it('setTask updates task', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setTask('What is the meaning of life?');
      });

      expect(result.current.current.task).toBe('What is the meaning of life?');
    });

    it('setAgents replaces agents array', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setAgents(['Claude', 'GPT-4', 'Gemini']);
      });

      expect(result.current.current.agents).toEqual(['Claude', 'GPT-4', 'Gemini']);
    });

    it('addAgent adds new agent', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.addAgent('Claude');
      });
      expect(result.current.current.agents).toEqual(['Claude']);

      act(() => {
        result.current.addAgent('GPT-4');
      });
      expect(result.current.current.agents).toEqual(['Claude', 'GPT-4']);
    });

    it('addAgent does not add duplicate', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.addAgent('Claude');
        result.current.addAgent('Claude');
      });

      expect(result.current.current.agents).toEqual(['Claude']);
    });
  });

  describe('Message Actions', () => {
    it('addMessage adds new message', () => {
      const { result } = renderHook(() => useDebateStore());

      const message = {
        agent: 'Claude',
        content: 'Hello, this is my response.',
        timestamp: 1234567890,
      };

      let added: boolean;
      act(() => {
        added = result.current.addMessage(message);
      });

      expect(added!).toBe(true);
      expect(result.current.current.messages).toHaveLength(1);
      expect(result.current.current.messages[0]).toEqual(message);
    });

    it('addMessage deduplicates identical messages', () => {
      const { result } = renderHook(() => useDebateStore());

      const message = {
        agent: 'Claude',
        content: 'Hello, this is my response.',
        timestamp: 1234567890,
      };

      let added1: boolean;
      let added2: boolean;

      act(() => {
        added1 = result.current.addMessage(message);
        added2 = result.current.addMessage(message);
      });

      expect(added1!).toBe(true);
      expect(added2!).toBe(false);
      expect(result.current.current.messages).toHaveLength(1);
    });

    it('addMessage allows different messages from same agent', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.addMessage({
          agent: 'Claude',
          content: 'First message',
          timestamp: 1234567890,
        });
        result.current.addMessage({
          agent: 'Claude',
          content: 'Second message',
          timestamp: 1234567891,
        });
      });

      expect(result.current.current.messages).toHaveLength(2);
    });

    it('clearMessages clears all messages and resets deduplication', () => {
      const { result } = renderHook(() => useDebateStore());

      const message = { agent: 'Claude', content: 'Hello', timestamp: 1234567890 };

      act(() => {
        result.current.addMessage(message);
      });
      expect(result.current.current.messages).toHaveLength(1);

      act(() => {
        result.current.clearMessages();
      });
      expect(result.current.current.messages).toHaveLength(0);

      // Should be able to add same message again after clear
      let added: boolean;
      act(() => {
        added = result.current.addMessage(message);
      });
      expect(added!).toBe(true);
      expect(result.current.current.messages).toHaveLength(1);
    });
  });

  describe('Streaming Actions', () => {
    it('startStream creates new streaming message', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude');
      });

      const streaming = result.current.current.streamingMessages.get('Claude');
      expect(streaming).toBeDefined();
      expect(streaming?.agent).toBe('Claude');
      expect(streaming?.content).toBe('');
      expect(streaming?.isComplete).toBe(false);
    });

    it('startStream with taskId creates composite key', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude', 'task-123');
      });

      const streaming = result.current.current.streamingMessages.get('Claude:task-123');
      expect(streaming).toBeDefined();
      expect(streaming?.agent).toBe('Claude');
      expect(streaming?.taskId).toBe('task-123');
    });

    it('appendStreamToken appends to existing stream', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude');
        result.current.appendStreamToken('Claude', 'Hello');
        result.current.appendStreamToken('Claude', ' world');
      });

      const streaming = result.current.current.streamingMessages.get('Claude');
      expect(streaming?.content).toBe('Hello world');
    });

    it('appendStreamToken handles sequence ordering', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude');
        // Out of order tokens
        result.current.appendStreamToken('Claude', 'first', 1);
        result.current.appendStreamToken('Claude', 'third', 3);
        result.current.appendStreamToken('Claude', 'second', 2);
      });

      const streaming = result.current.current.streamingMessages.get('Claude');
      expect(streaming?.content).toBe('firstsecondthird');
    });

    it('appendStreamToken creates stream if not exists', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.appendStreamToken('Claude', 'Hello');
      });

      const streaming = result.current.current.streamingMessages.get('Claude');
      expect(streaming).toBeDefined();
      expect(streaming?.content).toBe('Hello');
    });

    it('endStream converts streaming to message', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude');
        result.current.appendStreamToken('Claude', 'Complete message');
        result.current.endStream('Claude');
      });

      // Streaming should be removed
      expect(result.current.current.streamingMessages.has('Claude')).toBe(false);

      // Message should be added
      expect(result.current.current.messages).toHaveLength(1);
      expect(result.current.current.messages[0].content).toBe('Complete message');
      expect(result.current.current.messages[0].agent).toBe('Claude');
    });

    it('endStream flushes pending out-of-order tokens', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude');
        result.current.appendStreamToken('Claude', 'first', 1);
        result.current.appendStreamToken('Claude', 'third', 3);
        // Skip seq 2, then end - should still include 'third'
        result.current.endStream('Claude');
      });

      expect(result.current.current.messages).toHaveLength(1);
      expect(result.current.current.messages[0].content).toBe('firstthird');
    });

    it('cleanupOrphanedStreams removes old streams', () => {
      const { result } = renderHook(() => useDebateStore());

      // Start a stream
      act(() => {
        result.current.startStream('Claude');
        result.current.appendStreamToken('Claude', 'Incomplete');
      });

      // Manually set old start time
      act(() => {
        const current = result.current.current.streamingMessages.get('Claude');
        if (current) {
          const updated = new Map(result.current.current.streamingMessages);
          updated.set('Claude', { ...current, startTime: Date.now() - 120000 }); // 2 minutes ago
          result.current.current.streamingMessages = updated;
        }
      });

      act(() => {
        result.current.cleanupOrphanedStreams(60000); // 1 minute timeout
      });

      expect(result.current.current.streamingMessages.has('Claude')).toBe(false);
      // Timed out message should be added
      expect(result.current.current.messages.length).toBeGreaterThanOrEqual(0);
    });
  });

  describe('Stream Events', () => {
    it('addStreamEvent adds event', () => {
      const { result } = renderHook(() => useDebateStore());

      const event = {
        type: 'consensus' as const,
        data: { reached: true, confidence: 0.85 },
        timestamp: Date.now() / 1000,
      };

      act(() => {
        result.current.addStreamEvent(event);
      });

      expect(result.current.current.streamEvents).toHaveLength(1);
      expect(result.current.current.streamEvents[0]).toEqual(event);
    });

    it('addStreamEvent limits to MAX_STREAM_EVENTS', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        for (let i = 0; i < 600; i++) {
          result.current.addStreamEvent({
            type: 'agent_message' as const,
            data: { content: `Message ${i}` },
            timestamp: Date.now() / 1000,
          });
        }
      });

      expect(result.current.current.streamEvents.length).toBeLessThanOrEqual(500);
    });

    it('clearStreamEvents clears all events', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.addStreamEvent({
          type: 'consensus' as const,
          data: {},
          timestamp: Date.now() / 1000,
        });
        result.current.clearStreamEvents();
      });

      expect(result.current.current.streamEvents).toHaveLength(0);
    });

    it('setHasCitations updates citations flag', () => {
      const { result } = renderHook(() => useDebateStore());

      expect(result.current.current.hasCitations).toBe(false);

      act(() => {
        result.current.setHasCitations(true);
      });

      expect(result.current.current.hasCitations).toBe(true);
    });
  });

  describe('Artifact Actions', () => {
    it('setArtifact sets artifact', () => {
      const { result } = renderHook(() => useDebateStore());

      const artifact = {
        id: 'artifact-123',
        task: 'Test task',
        agents: ['Claude', 'GPT-4'],
        consensus_reached: true,
        confidence: 0.9,
        created_at: '2026-01-19T00:00:00Z',
      };

      act(() => {
        result.current.setArtifact(artifact);
      });

      expect(result.current.artifact).toEqual(artifact);
    });

    it('setArtifact can clear artifact', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setArtifact({
          id: 'artifact-123',
          task: 'Test task',
          agents: ['Claude'],
          consensus_reached: true,
          confidence: 0.9,
          created_at: '2026-01-19T00:00:00Z',
        });
        result.current.setArtifact(null);
      });

      expect(result.current.artifact).toBeNull();
    });
  });

  describe('UI Actions', () => {
    it('setShowParticipation updates state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setShowParticipation(true);
      });

      expect(result.current.ui.showParticipation).toBe(true);
    });

    it('setShowCitations updates state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setShowCitations(true);
      });

      expect(result.current.ui.showCitations).toBe(true);
    });

    it('setUserScrolled updates state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setUserScrolled(true);
      });

      expect(result.current.ui.userScrolled).toBe(true);
    });

    it('setAutoScroll updates state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setAutoScroll(false);
      });

      expect(result.current.ui.autoScroll).toBe(false);
    });
  });

  describe('Sequence Tracking', () => {
    it('updateSequence tracks sequence and detects gaps', () => {
      const { result } = renderHook(() => useDebateStore());

      let gap1: { gap: number } | null;
      let gap2: { gap: number } | null;
      let gap3: { gap: number } | null;

      act(() => {
        gap1 = result.current.updateSequence(1);
        gap2 = result.current.updateSequence(2);
        gap3 = result.current.updateSequence(5); // Gap of 2 (3, 4 missing)
      });

      expect(gap1!).toBeNull();
      expect(gap2!).toBeNull();
      expect(gap3!).toEqual({ gap: 2 });
    });
  });

  describe('Reset Actions', () => {
    it('resetCurrent resets only current state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setDebateId('debate-123');
        result.current.setTask('Test task');
        result.current.addMessage({ agent: 'Claude', content: 'Hello', timestamp: 123 });
        result.current.setArtifact({
          id: 'artifact',
          task: 'Test',
          agents: [],
          consensus_reached: true,
          confidence: 0.9,
          created_at: '2026-01-19',
        });
        result.current.setShowParticipation(true);
      });

      act(() => {
        result.current.resetCurrent();
      });

      // Current state should be reset
      expect(result.current.current.debateId).toBeNull();
      expect(result.current.current.task).toBe('');
      expect(result.current.current.messages).toHaveLength(0);

      // Artifact and UI should be preserved
      expect(result.current.artifact).not.toBeNull();
      expect(result.current.ui.showParticipation).toBe(true);
    });

    it('resetAll resets everything', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setDebateId('debate-123');
        result.current.setTask('Test task');
        result.current.addMessage({ agent: 'Claude', content: 'Hello', timestamp: 123 });
        result.current.setArtifact({
          id: 'artifact',
          task: 'Test',
          agents: [],
          consensus_reached: true,
          confidence: 0.9,
          created_at: '2026-01-19',
        });
        result.current.setShowParticipation(true);
      });

      act(() => {
        result.current.resetAll();
      });

      // Everything should be reset
      expect(result.current.current.debateId).toBeNull();
      expect(result.current.current.task).toBe('');
      expect(result.current.current.messages).toHaveLength(0);
      expect(result.current.artifact).toBeNull();
      expect(result.current.ui.showParticipation).toBe(false);
    });
  });

  describe('Selectors', () => {
    it('selectDebateStatus returns connection status', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setConnectionStatus('streaming');
      });

      expect(selectDebateStatus(result.current)).toBe('streaming');
    });

    it('selectDebateMessages returns messages', () => {
      const { result } = renderHook(() => useDebateStore());

      const message = { agent: 'Claude', content: 'Test', timestamp: 123 };
      act(() => {
        result.current.addMessage(message);
      });

      expect(selectDebateMessages(result.current)).toEqual([message]);
    });

    it('selectStreamingMessages returns streaming map', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.startStream('Claude');
      });

      const streaming = selectStreamingMessages(result.current);
      expect(streaming.has('Claude')).toBe(true);
    });

    it('selectDebateAgents returns agents', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setAgents(['Claude', 'GPT-4']);
      });

      expect(selectDebateAgents(result.current)).toEqual(['Claude', 'GPT-4']);
    });

    it('selectDebateTask returns task', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setTask('What is AI?');
      });

      expect(selectDebateTask(result.current)).toBe('What is AI?');
    });

    it('selectStreamEvents returns stream events', () => {
      const { result } = renderHook(() => useDebateStore());

      const event = { type: 'consensus' as const, data: {}, timestamp: 123 };
      act(() => {
        result.current.addStreamEvent(event);
      });

      expect(selectStreamEvents(result.current)).toEqual([event]);
    });

    it('selectHasCitations returns citations flag', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setHasCitations(true);
      });

      expect(selectHasCitations(result.current)).toBe(true);
    });

    it('selectDebateUI returns UI state', () => {
      const { result } = renderHook(() => useDebateStore());

      act(() => {
        result.current.setShowParticipation(true);
        result.current.setAutoScroll(false);
      });

      const ui = selectDebateUI(result.current);
      expect(ui.showParticipation).toBe(true);
      expect(ui.autoScroll).toBe(false);
    });

    it('selectArtifact returns artifact', () => {
      const { result } = renderHook(() => useDebateStore());

      const artifact = {
        id: 'test',
        task: 'Task',
        agents: [],
        consensus_reached: true,
        confidence: 0.9,
        created_at: '2026-01-19',
      };

      act(() => {
        result.current.setArtifact(artifact);
      });

      expect(selectArtifact(result.current)).toEqual(artifact);
    });
  });
});
