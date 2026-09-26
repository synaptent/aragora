/**
 * Aragora Stream Manager
 *
 * Manages WebSocket connections for real-time updates from the Aragora API.
 * Integrates with the existing streamClient.ts for event handling.
 */

import * as vscode from 'vscode';
import type {
  ExtensionMessage,
  DebateMessage,
  DebateConsensus,
  DebateState,
  Agent,
  TokenUsage,
} from '../types/messages';

interface StreamEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

interface DeliberationStartedEvent extends StreamEvent {
  type: 'deliberation_started';
  data: { debate_id: string; question: string; agents: string[]; rounds: number };
}

interface AgentMessageEvent extends StreamEvent {
  type: 'agent_message';
  data: {
    debate_id: string;
    agent: string;
    content: string;
    round: number;
    tokens?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  };
}

interface ConsensusEvent extends StreamEvent {
  type: 'deliberation_consensus';
  data: {
    debate_id: string;
    answer: string;
    confidence: number;
    method: string;
    agreeing_agents: string[];
    dissent?: Array<{ agent: string; reason: string }>;
  };
}

interface TaskCompletedEvent extends StreamEvent {
  type: 'task_completed';
  data: { task_id: string; result: unknown };
}

type AnyStreamEvent =
  DeliberationStartedEvent | AgentMessageEvent | ConsensusEvent | TaskCompletedEvent | StreamEvent;

export type StreamEventHandler = (event: ExtensionMessage) => void;

export class StreamManager implements vscode.Disposable {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private handlers: Set<StreamEventHandler> = new Set();
  private connectionStatus: 'connected' | 'disconnected' | 'connecting' = 'disconnected';
  private statusBarItem: vscode.StatusBarItem;
  private disposables: vscode.Disposable[] = [];

  // Active debates being tracked
  private activeDebates: Map<string, DebateState> = new Map();

  constructor() {
    // Create status bar item for connection status
    this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
    this.statusBarItem.command = 'aragora.toggleStream';
    this.updateStatusBar();

    // Register commands
    this.disposables.push(
      vscode.commands.registerCommand('aragora.toggleStream', () => {
        if (this.connectionStatus === 'connected') {
          this.disconnect();
        } else {
          this.connect();
        }
      }),
    );
  }

  /**
   * Connect to the WebSocket stream
   */
  async connect(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    this.setConnectionStatus('connecting');

    const config = vscode.workspace.getConfiguration('aragora');
    const apiUrl = config.get<string>('apiUrl') || 'https://api.aragora.ai';
    const apiKey = config.get<string>('apiKey') || '';

    // Convert HTTP to WebSocket URL
    const wsUrl = apiUrl.replace(/^http/, 'ws') + '/ws/stream';

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.setConnectionStatus('connected');
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;

        // Send authentication if we have an API key
        if (apiKey) {
          this.ws?.send(JSON.stringify({ type: 'auth', token: apiKey }));
        }

        // Start ping interval to keep connection alive
        this.startPingInterval();

        vscode.window.showInformationMessage('Connected to Aragora stream');
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as AnyStreamEvent;
          this.handleStreamEvent(data);
        } catch (error) {
          console.error('Failed to parse stream event:', error);
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      this.ws.onclose = (event) => {
        this.setConnectionStatus('disconnected');
        this.stopPingInterval();

        if (event.code !== 1000) {
          // Abnormal close - attempt reconnect
          this.scheduleReconnect();
        }
      };
    } catch (error) {
      console.error('Failed to connect:', error);
      this.setConnectionStatus('disconnected');
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from the WebSocket stream
   */
  disconnect(): void {
    this.stopPingInterval();
    this.cancelReconnect();

    if (this.ws) {
      this.ws.close(1000, 'User disconnect');
      this.ws = null;
    }

    this.setConnectionStatus('disconnected');
    vscode.window.showInformationMessage('Disconnected from Aragora stream');
  }

  /**
   * Subscribe to stream events
   */
  subscribe(handler: StreamEventHandler): vscode.Disposable {
    this.handlers.add(handler);
    return { dispose: () => this.handlers.delete(handler) };
  }

  /**
   * Get current connection status
   */
  getConnectionStatus(): 'connected' | 'disconnected' | 'connecting' {
    return this.connectionStatus;
  }

  /**
   * Get an active debate by ID
   */
  getDebate(debateId: string): DebateState | undefined {
    return this.activeDebates.get(debateId);
  }

  /**
   * Send a message through the WebSocket
   */
  send(message: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  private handleStreamEvent(event: AnyStreamEvent): void {
    const message = this.transformEvent(event);
    if (message) {
      // Notify all subscribers
      for (const handler of this.handlers) {
        try {
          handler(message);
        } catch (error) {
          console.error('Handler error:', error);
        }
      }
    }
  }

  private transformEvent(event: AnyStreamEvent): ExtensionMessage | null {
    switch (event.type) {
      case 'deliberation_started': {
        const e = event as DeliberationStartedEvent;
        const debate: DebateState = {
          id: e.data.debate_id,
          question: e.data.question,
          status: 'running',
          currentRound: 1,
          totalRounds: e.data.rounds,
          messages: [],
          startTime: event.timestamp,
        };
        this.activeDebates.set(debate.id, debate);
        return { type: 'debate_started', debate };
      }

      case 'agent_message': {
        const e = event as AgentMessageEvent;
        const debate = this.activeDebates.get(e.data.debate_id);
        if (!debate) return null;

        const message: DebateMessage = {
          id: `${e.data.debate_id}-${Date.now()}`,
          agent: {
            id: e.data.agent,
            name: e.data.agent,
            provider: this.guessProvider(e.data.agent),
          },
          content: e.data.content,
          round: e.data.round,
          timestamp: event.timestamp,
          tokens: e.data.tokens
            ? {
                promptTokens: e.data.tokens.prompt_tokens,
                completionTokens: e.data.tokens.completion_tokens,
                totalTokens: e.data.tokens.total_tokens,
              }
            : undefined,
        };

        debate.messages.push(message);
        debate.currentRound = e.data.round;

        return { type: 'agent_message', message };
      }

      case 'deliberation_consensus': {
        const e = event as ConsensusEvent;
        const debate = this.activeDebates.get(e.data.debate_id);
        if (!debate) return null;

        const consensus: DebateConsensus = {
          answer: e.data.answer,
          confidence: e.data.confidence,
          method: e.data.method as 'majority' | 'unanimous' | 'synthesis' | 'weighted',
          agreeingAgents: e.data.agreeing_agents,
          dissent: e.data.dissent,
        };

        debate.consensus = consensus;
        debate.status = 'completed';
        debate.endTime = event.timestamp;

        return { type: 'consensus_reached', consensus };
      }

      case 'task_completed': {
        const e = event as TaskCompletedEvent;
        // Trigger refresh of task tree
        vscode.commands.executeCommand('aragora.refreshControlPlane');
        return { type: 'info', message: `Task ${e.data.task_id} completed` };
      }

      default:
        return null;
    }
  }

  private guessProvider(agentName: string): string {
    const name = agentName.toLowerCase();
    if (name.includes('claude')) return 'anthropic';
    if (name.includes('gpt')) return 'openai';
    if (name.includes('gemini')) return 'google';
    if (name.includes('mistral')) return 'mistral';
    if (name.includes('grok')) return 'xai';
    if (name.includes('llama')) return 'meta';
    return 'unknown';
  }

  private setConnectionStatus(status: 'connected' | 'disconnected' | 'connecting'): void {
    this.connectionStatus = status;
    this.updateStatusBar();
  }

  private updateStatusBar(): void {
    switch (this.connectionStatus) {
      case 'connected':
        this.statusBarItem.text = '$(broadcast) Aragora Live';
        this.statusBarItem.tooltip = 'Connected to Aragora stream. Click to disconnect.';
        this.statusBarItem.backgroundColor = undefined;
        break;
      case 'connecting':
        this.statusBarItem.text = '$(sync~spin) Connecting...';
        this.statusBarItem.tooltip = 'Connecting to Aragora stream...';
        this.statusBarItem.backgroundColor = undefined;
        break;
      case 'disconnected':
        this.statusBarItem.text = '$(broadcast) Aragora Offline';
        this.statusBarItem.tooltip = 'Disconnected from Aragora stream. Click to connect.';
        this.statusBarItem.backgroundColor = new vscode.ThemeColor(
          'statusBarItem.warningBackground',
        );
        break;
    }
    this.statusBarItem.show();
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      vscode.window.showErrorMessage('Failed to connect to Aragora stream after multiple attempts');
      return;
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.connect();
    }, this.reconnectDelay);
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startPingInterval(): void {
    this.pingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  }

  private stopPingInterval(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  dispose(): void {
    this.disconnect();
    this.statusBarItem.dispose();
    this.disposables.forEach((d) => d.dispose());
  }
}
