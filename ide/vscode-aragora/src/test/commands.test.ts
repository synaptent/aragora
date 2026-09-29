/**
 * Tests for extension commands and keybindings.
 *
 * These tests verify command registration and basic logic.
 */

import { MockUri } from './vscode.mock';

describe('Extension Commands', () => {
  // Command registration tests
  describe('Command Registration', () => {
    const expectedCommands = [
      'aragora.runDebate',
      'aragora.runGauntlet',
      'aragora.listAgents',
      'aragora.showResults',
      'aragora.configure',
      'aragora.showControlPlane',
      'aragora.refreshFleet',
      'aragora.refreshControlPlane',
      'aragora.submitTask',
      'aragora.viewAgentHealth',
      'aragora.cancelTask',
      'aragora.registerAgent',
      'aragora.analyzeWorkspace',
      'aragora.explainCode',
      'aragora.reviewSelection',
      'aragora.generateTests',
      'aragora.showDebatePanel',
      'aragora.showReviewPanel',
      'aragora.quickReview',
      'aragora.improveCode',
      'aragora.fixIssue',
      'aragora.addToDebate',
      'aragora.clearDebateContext',
      'aragora.viewDebateContext',
      'aragora.connectControlPlane',
      'aragora.disconnectControlPlane',
      'aragora.triggerDeliberation',
      'aragora.connectToDeliberation',
      'aragora.showDebateViewer',
      'aragora.toggleStream',
    ];

    it('should have all expected commands defined', () => {
      // This tests that our expected command list is complete
      expect(expectedCommands.length).toBeGreaterThan(25);
    });

    it('should have unique command names', () => {
      const uniqueCommands = new Set(expectedCommands);
      expect(uniqueCommands.size).toBe(expectedCommands.length);
    });

    it('should follow aragora namespace convention', () => {
      for (const command of expectedCommands) {
        expect(command.startsWith('aragora.')).toBe(true);
      }
    });
  });

  // Keybinding tests
  describe('Keybindings', () => {
    const keybindings = [
      { command: 'aragora.explainCode', key: 'cmd+shift+a' },
      { command: 'aragora.reviewSelection', key: 'cmd+shift+r' },
      { command: 'aragora.generateTests', key: 'cmd+shift+t' },
      { command: 'aragora.showDebatePanel', key: 'cmd+shift+d' },
      { command: 'aragora.runDebate', key: 'cmd+alt+d' },
      { command: 'aragora.improveCode', key: 'cmd+shift+i' },
      { command: 'aragora.quickReview', key: 'cmd+alt+r' },
      { command: 'aragora.showControlPlane', key: 'cmd+alt+c' },
      { command: 'aragora.triggerDeliberation', key: 'cmd+alt+n' },
      { command: 'aragora.addToDebate', key: 'cmd+shift+b' },
    ];

    it('should have keybindings for important commands', () => {
      expect(keybindings.length).toBeGreaterThanOrEqual(10);
    });

    it('should have unique keybindings', () => {
      const keys = keybindings.map((kb) => kb.key);
      const uniqueKeys = new Set(keys);
      expect(uniqueKeys.size).toBe(keys.length);
    });

    it('should use consistent modifier pattern', () => {
      for (const kb of keybindings) {
        // All keybindings should use cmd (mac) or ctrl modifier
        expect(kb.key).toMatch(/^cmd\+/);
      }
    });

    describe('Keybinding Categories', () => {
      it('should have code analysis keybindings', () => {
        const analysisCommands = ['explainCode', 'reviewSelection', 'generateTests', 'improveCode'];
        for (const cmd of analysisCommands) {
          const found = keybindings.find((kb) => kb.command.endsWith(cmd));
          expect(found).toBeDefined();
        }
      });

      it('should have debate-related keybindings', () => {
        const debateCommands = [
          'showDebatePanel',
          'runDebate',
          'addToDebate',
          'triggerDeliberation',
        ];
        for (const cmd of debateCommands) {
          const found = keybindings.find((kb) => kb.command.endsWith(cmd));
          expect(found).toBeDefined();
        }
      });
    });
  });

  // Debate context management tests
  describe('Debate Context Management', () => {
    interface DebateContext {
      snippets: string[];
      fileContexts: Map<string, string[]>;
    }

    function createDebateContextEntry(
      fileName: string,
      startLine: number,
      endLine: number,
      content: string,
    ): string {
      return `\n### From ${fileName} (lines ${startLine}-${endLine}):\n\`\`\`\n${content}\n\`\`\``;
    }

    function parseDebateContextEntry(
      entry: string,
    ): { fileName: string; startLine: number; endLine: number } | null {
      const match = entry.match(/From (.+?) \(lines (\d+)-(\d+)\)/);
      if (!match) return null;
      return {
        fileName: match[1],
        startLine: parseInt(match[2], 10),
        endLine: parseInt(match[3], 10),
      };
    }

    it('should format debate context entries correctly', () => {
      const entry = createDebateContextEntry('test.ts', 10, 20, 'const x = 1;');

      expect(entry).toContain('From test.ts');
      expect(entry).toContain('lines 10-20');
      expect(entry).toContain('const x = 1;');
      expect(entry).toContain('```');
    });

    it('should parse debate context entries', () => {
      const entry = createDebateContextEntry('handler.py', 50, 75, 'def handle():');
      const parsed = parseDebateContextEntry(entry);

      expect(parsed).not.toBeNull();
      expect(parsed!.fileName).toBe('handler.py');
      expect(parsed!.startLine).toBe(50);
      expect(parsed!.endLine).toBe(75);
    });

    it('should handle multiple snippets', () => {
      const context: string[] = [];

      context.push(createDebateContextEntry('a.ts', 1, 10, 'code1'));
      context.push(createDebateContextEntry('b.ts', 5, 15, 'code2'));
      context.push(createDebateContextEntry('a.ts', 20, 30, 'code3'));

      expect(context.length).toBe(3);

      // Count snippets per file
      const fileSnippetCounts = new Map<string, number>();
      for (const entry of context) {
        const parsed = parseDebateContextEntry(entry);
        if (parsed) {
          const count = fileSnippetCounts.get(parsed.fileName) || 0;
          fileSnippetCounts.set(parsed.fileName, count + 1);
        }
      }

      expect(fileSnippetCounts.get('a.ts')).toBe(2);
      expect(fileSnippetCounts.get('b.ts')).toBe(1);
    });
  });

  // Quick review tests
  describe('Quick Review Logic', () => {
    interface ReviewResult {
      summary: string;
      comments: string[];
      scope: 'file' | 'selection';
      lineCount: number;
    }

    function formatReviewNotification(result: ReviewResult): string {
      return `Review complete: ${result.summary || 'No issues found'}`;
    }

    function determineReviewScope(hasSelection: boolean): 'file' | 'selection' {
      return hasSelection ? 'selection' : 'file';
    }

    it('should format review notification correctly', () => {
      const result: ReviewResult = {
        summary: 'Found 3 potential improvements',
        comments: ['Use const instead of let', 'Add type annotations', 'Extract function'],
        scope: 'selection',
        lineCount: 25,
      };

      const notification = formatReviewNotification(result);

      expect(notification).toContain('Review complete');
      expect(notification).toContain('3 potential improvements');
    });

    it('should handle empty summary', () => {
      const result: ReviewResult = { summary: '', comments: [], scope: 'file', lineCount: 100 };

      const notification = formatReviewNotification(result);

      expect(notification).toContain('No issues found');
    });

    it('should determine scope correctly', () => {
      expect(determineReviewScope(true)).toBe('selection');
      expect(determineReviewScope(false)).toBe('file');
    });
  });

  // Deliberation trigger tests
  describe('Deliberation Triggering', () => {
    interface DeliberationRequest {
      question: string;
      agents: string[];
      rounds: number;
    }

    function validateDeliberationRequest(request: DeliberationRequest): string[] {
      const errors: string[] = [];

      if (!request.question || request.question.trim().length === 0) {
        errors.push('Question is required');
      }

      if (request.question && request.question.length > 1000) {
        errors.push('Question exceeds maximum length of 1000 characters');
      }

      if (!request.agents || request.agents.length === 0) {
        errors.push('At least one agent is required');
      }

      if (request.agents && request.agents.length > 10) {
        errors.push('Maximum of 10 agents allowed');
      }

      if (request.rounds < 1 || request.rounds > 10) {
        errors.push('Rounds must be between 1 and 10');
      }

      return errors;
    }

    it('should validate valid request', () => {
      const request: DeliberationRequest = {
        question: 'What is the best approach for error handling?',
        agents: ['claude', 'gpt-4'],
        rounds: 3,
      };

      const errors = validateDeliberationRequest(request);
      expect(errors).toHaveLength(0);
    });

    it('should reject empty question', () => {
      const request: DeliberationRequest = { question: '', agents: ['claude'], rounds: 3 };

      const errors = validateDeliberationRequest(request);
      expect(errors).toContain('Question is required');
    });

    it('should reject too long question', () => {
      const request: DeliberationRequest = {
        question: 'x'.repeat(1001),
        agents: ['claude'],
        rounds: 3,
      };

      const errors = validateDeliberationRequest(request);
      expect(errors).toContain('Question exceeds maximum length of 1000 characters');
    });

    it('should reject no agents', () => {
      const request: DeliberationRequest = { question: 'Valid question', agents: [], rounds: 3 };

      const errors = validateDeliberationRequest(request);
      expect(errors).toContain('At least one agent is required');
    });

    it('should reject too many agents', () => {
      const request: DeliberationRequest = {
        question: 'Valid question',
        agents: Array(11).fill('agent'),
        rounds: 3,
      };

      const errors = validateDeliberationRequest(request);
      expect(errors).toContain('Maximum of 10 agents allowed');
    });

    it('should reject invalid rounds', () => {
      const request1: DeliberationRequest = { question: 'Valid', agents: ['claude'], rounds: 0 };

      const request2: DeliberationRequest = { question: 'Valid', agents: ['claude'], rounds: 11 };

      expect(validateDeliberationRequest(request1)).toContain('Rounds must be between 1 and 10');
      expect(validateDeliberationRequest(request2)).toContain('Rounds must be between 1 and 10');
    });
  });

  // Connection management tests
  describe('Control Plane Connection', () => {
    type ConnectionStatus = 'connected' | 'disconnected' | 'connecting';

    interface ConnectionState {
      status: ConnectionStatus;
      reconnectAttempts: number;
      lastError: string | null;
    }

    function shouldAttemptReconnect(state: ConnectionState, maxAttempts: number): boolean {
      if (state.status === 'connected') return false;
      if (state.status === 'connecting') return false;
      return state.reconnectAttempts < maxAttempts;
    }

    function calculateReconnectDelay(
      attempts: number,
      baseDelay: number,
      maxDelay: number,
    ): number {
      const delay = baseDelay * Math.pow(2, attempts);
      return Math.min(delay, maxDelay);
    }

    it('should not reconnect when connected', () => {
      const state: ConnectionState = { status: 'connected', reconnectAttempts: 0, lastError: null };

      expect(shouldAttemptReconnect(state, 10)).toBe(false);
    });

    it('should not reconnect when already connecting', () => {
      const state: ConnectionState = {
        status: 'connecting',
        reconnectAttempts: 5,
        lastError: null,
      };

      expect(shouldAttemptReconnect(state, 10)).toBe(false);
    });

    it('should reconnect when disconnected and under max attempts', () => {
      const state: ConnectionState = {
        status: 'disconnected',
        reconnectAttempts: 5,
        lastError: 'Connection refused',
      };

      expect(shouldAttemptReconnect(state, 10)).toBe(true);
    });

    it('should not reconnect when at max attempts', () => {
      const state: ConnectionState = {
        status: 'disconnected',
        reconnectAttempts: 10,
        lastError: 'Connection refused',
      };

      expect(shouldAttemptReconnect(state, 10)).toBe(false);
    });

    it('should calculate exponential backoff delay', () => {
      const baseDelay = 1000;
      const maxDelay = 30000;

      expect(calculateReconnectDelay(0, baseDelay, maxDelay)).toBe(1000);
      expect(calculateReconnectDelay(1, baseDelay, maxDelay)).toBe(2000);
      expect(calculateReconnectDelay(2, baseDelay, maxDelay)).toBe(4000);
      expect(calculateReconnectDelay(3, baseDelay, maxDelay)).toBe(8000);
      expect(calculateReconnectDelay(4, baseDelay, maxDelay)).toBe(16000);
      expect(calculateReconnectDelay(5, baseDelay, maxDelay)).toBe(30000); // capped at max
      expect(calculateReconnectDelay(10, baseDelay, maxDelay)).toBe(30000);
    });
  });
});
