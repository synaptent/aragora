/**
 * Aragora WebSocket Client
 *
 * Provides real-time streaming for debate events, agent messages, and consensus.
 */

import type {
  AragoraConfig,
  WebSocketEvent,
  DebateStartEvent,
  RoundStartEvent,
  AgentMessageEvent,
  CritiqueEvent,
  VoteEvent,
  ConsensusEvent,
  DebateEndEvent,
  SynthesisEvent,
  RevisionEvent,
  PhaseChangeEvent,
  AudienceSuggestionEvent,
  UserVoteEvent,
  WarningEvent,
} from './types';
import { ConnectionError } from './errors';

// Keep Node fallback local to this file without requiring global @types/node.
declare const require: (moduleName: string) => unknown;

export type WebSocketState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

export interface WebSocketOptions {
  /** Auto-reconnect on disconnect (default: true) */
  autoReconnect?: boolean;
  /** Maximum reconnection attempts (default: 5) */
  maxReconnectAttempts?: number;
  /** Base delay between reconnection attempts in ms (default: 1000) */
  reconnectDelay?: number;
  /** Heartbeat interval in ms (default: 30000) */
  heartbeatInterval?: number;
}

type EventHandler<T> = (event: T) => void;

interface EventHandlers {
  connected: EventHandler<void>[];
  disconnected: EventHandler<{ code: number; reason: string }>[];
  error: EventHandler<Error>[];
  debate_start: EventHandler<DebateStartEvent>[];
  round_start: EventHandler<RoundStartEvent>[];
  agent_message: EventHandler<AgentMessageEvent>[];
  propose: EventHandler<AgentMessageEvent>[];
  critique: EventHandler<CritiqueEvent>[];
  revision: EventHandler<RevisionEvent>[];
  synthesis: EventHandler<SynthesisEvent>[];
  vote: EventHandler<VoteEvent>[];
  consensus: EventHandler<ConsensusEvent>[];
  consensus_reached: EventHandler<ConsensusEvent>[];
  debate_end: EventHandler<DebateEndEvent>[];
  phase_change: EventHandler<PhaseChangeEvent>[];
  audience_suggestion: EventHandler<AudienceSuggestionEvent>[];
  user_vote: EventHandler<UserVoteEvent>[];
  warning: EventHandler<WarningEvent>[];
  message: EventHandler<WebSocketEvent>[];
}

export class AragoraWebSocket {
  private ws: WebSocket | null = null;
  private config: AragoraConfig;
  private options: Required<WebSocketOptions>;
  private state: WebSocketState = 'disconnected';
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private handlers: EventHandlers = {
    connected: [],
    disconnected: [],
    error: [],
    debate_start: [],
    round_start: [],
    agent_message: [],
    propose: [],
    critique: [],
    revision: [],
    synthesis: [],
    vote: [],
    consensus: [],
    consensus_reached: [],
    debate_end: [],
    phase_change: [],
    audience_suggestion: [],
    user_vote: [],
    warning: [],
    message: [],
  };

  constructor(config: AragoraConfig, options: WebSocketOptions = {}) {
    this.config = config;
    this.options = {
      autoReconnect: options.autoReconnect ?? true,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 5,
      reconnectDelay: options.reconnectDelay ?? 1000,
      heartbeatInterval: options.heartbeatInterval ?? 30000,
    };
  }

  /**
   * Get the current connection state.
   */
  getState(): WebSocketState {
    return this.state;
  }

  /**
   * Connect to the WebSocket server.
   */
  async connect(debateId?: string): Promise<void> {
    if (this.state === 'connected' || this.state === 'connecting') {
      return;
    }

    this.state = 'connecting';

    const wsUrl = this.buildWsUrl(debateId);

    return new Promise((resolve, reject) => {
      try {
        // Use native WebSocket in browser, or require ws for Node.js
        if (typeof WebSocket !== 'undefined') {
          this.ws = new WebSocket(wsUrl);
        } else {
          // Node.js environment - dynamically import ws
          // eslint-disable-next-line @typescript-eslint/no-require-imports
          const WS = require('ws') as new (url: string) => WebSocket;
          this.ws = new WS(wsUrl);
        }

        this.ws!.onopen = () => {
          this.state = 'connected';
          this.reconnectAttempts = 0;
          this.startHeartbeat();
          this.emit('connected', undefined);
          resolve();
        };

        this.ws!.onclose = (event) => {
          this.handleDisconnect(event.code, event.reason);
        };

        this.ws!.onerror = (_event) => {
          const error = new Error('WebSocket error');
          this.emit('error', error);
          if (this.state === 'connecting') {
            reject(error);
          }
        };

        this.ws!.onmessage = (event) => {
          this.handleMessage(event.data as string);
        };
      } catch (error) {
        this.state = 'disconnected';
        reject(error);
      }
    });
  }

  /**
   * Disconnect from the WebSocket server.
   */
  disconnect(): void {
    this.options.autoReconnect = false;
    this.cleanup();
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.state = 'disconnected';
  }

  /**
   * Subscribe to a specific debate's events.
   */
  subscribe(debateId: string): void {
    this.send({
      type: 'subscribe',
      debate_id: debateId,
    });
  }

  /**
   * Unsubscribe from a debate's events.
   */
  unsubscribe(debateId: string): void {
    this.send({
      type: 'unsubscribe',
      debate_id: debateId,
    });
  }

  /**
   * Send a message to the server.
   */
  send(data: Record<string, unknown>): void {
    if (this.ws && this.state === 'connected') {
      this.ws.send(JSON.stringify(data));
    }
  }

  // Event handlers
  on(event: 'connected', handler: EventHandler<void>): () => void;
  on(event: 'disconnected', handler: EventHandler<{ code: number; reason: string }>): () => void;
  on(event: 'error', handler: EventHandler<Error>): () => void;
  on(event: 'debate_start', handler: EventHandler<DebateStartEvent>): () => void;
  on(event: 'round_start', handler: EventHandler<RoundStartEvent>): () => void;
  on(event: 'agent_message', handler: EventHandler<AgentMessageEvent>): () => void;
  on(event: 'critique', handler: EventHandler<CritiqueEvent>): () => void;
  on(event: 'vote', handler: EventHandler<VoteEvent>): () => void;
  on(event: 'consensus', handler: EventHandler<ConsensusEvent>): () => void;
  on(event: 'debate_end', handler: EventHandler<DebateEndEvent>): () => void;
  on(event: 'message', handler: EventHandler<WebSocketEvent>): () => void;
  on<K extends keyof EventHandlers>(event: K, handler: EventHandlers[K][number]): () => void {
    // TypeScript can't infer indexed mapped type assignments - cast to unknown[] is safe here
    (this.handlers[event] as unknown[]).push(handler);
    return () => this.off(event, handler);
  }

  /**
   * Remove an event handler.
   */
  off<K extends keyof EventHandlers>(event: K, handler: EventHandlers[K][number]): void {
    // TypeScript can't infer indexed mapped type assignments - cast to unknown[] is safe here
    const handlers = this.handlers[event] as unknown[];
    const index = handlers.indexOf(handler);
    if (index !== -1) {
      handlers.splice(index, 1);
    }
  }

  /**
   * Wait for a specific event to occur.
   * Returns a promise that resolves with the event data.
   */
  once<K extends keyof EventHandlers>(event: K): Promise<Parameters<EventHandlers[K][number]>[0]> {
    type EventData = Parameters<EventHandlers[K][number]>[0];
    return new Promise((resolve) => {
      // Handler that removes itself after first call
      const handler = (data: EventData) => {
        // Remove handler - use unknown[] for indexed type compatibility
        (this.handlers[event] as unknown[]).splice(
          (this.handlers[event] as unknown[]).indexOf(handler),
          1
        );
        resolve(data);
      };
      // Add handler - use unknown[] for indexed type compatibility
      (this.handlers[event] as unknown[]).push(handler);
    });
  }

  private buildWsUrl(debateId?: string): string {
    let wsUrl = this.config.wsUrl;

    if (!wsUrl) {
      // Convert HTTP URL to WebSocket URL
      wsUrl = this.config.baseUrl
        .replace(/^http:/, 'ws:')
        .replace(/^https:/, 'wss:');
    }

    // Ensure path ends with /ws
    if (!wsUrl.endsWith('/ws')) {
      wsUrl = wsUrl.replace(/\/?$/, '/ws');
    }

    // Add debate ID if provided
    if (debateId) {
      wsUrl += `?debate_id=${encodeURIComponent(debateId)}`;
    }

    // Add auth token if available
    if (this.config.apiKey) {
      const separator = debateId ? '&' : '?';
      wsUrl += `${separator}token=${encodeURIComponent(this.config.apiKey)}`;
    }

    return wsUrl;
  }

  private handleMessage(data: string): void {
    try {
      const event = JSON.parse(data) as WebSocketEvent;

      // Emit to generic message handlers
      this.emit('message', event);

      // Emit to specific event type handlers - event.data type varies by event type
      const eventType = event.type as keyof EventHandlers;
      if (eventType in this.handlers) {
        // Cast to unknown is safe - emit() will pass to correctly-typed handlers
        this.emit(eventType, event.data as Parameters<EventHandlers[typeof eventType][number]>[0]);
      }
    } catch (_error) {
      this.emit('error', new Error(`Failed to parse message: ${data}`));
    }
  }

  private handleDisconnect(code: number, reason: string): void {
    this.cleanup();
    this.state = 'disconnected';
    this.emit('disconnected', { code, reason });

    if (this.options.autoReconnect && this.reconnectAttempts < this.options.maxReconnectAttempts) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    this.state = 'reconnecting';
    const delay = this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      this.connect().catch(() => {
        // Reconnect failed, will be handled by onclose
      });
    }, delay);
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'ping' });
    }, this.options.heartbeatInterval);
  }

  private cleanup(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private emit<K extends keyof EventHandlers>(
    event: K,
    data: Parameters<EventHandlers[K][number]>[0]
  ): void {
    for (const handler of this.handlers[event]) {
      try {
        (handler as (data: unknown) => void)(data);
      } catch (error) {
        console.error(`Error in ${event} handler:`, error);
      }
    }
  }
}

/**
 * Create a WebSocket client for streaming debate events.
 */
export function createWebSocket(
  config: AragoraConfig,
  options?: WebSocketOptions
): AragoraWebSocket {
  return new AragoraWebSocket(config, options);
}

// =============================================================================
// Async Iterator Support
// =============================================================================

export interface StreamOptions extends WebSocketOptions {
  /** Filter events to only this debate ID */
  debateId?: string;
}

/**
 * Helper to extract loop/debate ID from an event.
 */
function getEventDebateId(event: WebSocketEvent): string | undefined {
  const data = event.data as Record<string, unknown> | undefined;
  const loopId = 'loop_id' in event ? (event as { loop_id?: string }).loop_id : undefined;
  return (
    event.debate_id ||
    loopId ||
    (typeof data?.debate_id === 'string' ? data.debate_id : undefined) ||
    (typeof data?.loop_id === 'string' ? data.loop_id : undefined)
  );
}

/**
 * Create an async iterable stream for debate events.
 *
 * This provides a convenient way to consume debate events using async iteration.
 * The stream handles connection and cleanup, draining accepted events before ending.
 * A disconnect without a server terminal event raises ConnectionError after draining;
 * it does not imply debate completion or resume this iterator on reconnection.
 *
 * @param config - Aragora configuration (baseUrl, apiKey, etc.)
 * @param options - Stream options including optional debateId filter
 * @returns AsyncGenerator that yields WebSocket events
 *
 * @example
 * ```typescript
 * import { streamDebate } from '@aragora/sdk';
 *
 * const config = { baseUrl: 'http://localhost:8080' };
 * const stream = streamDebate(config, { debateId: 'my-debate-id' });
 *
 * for await (const event of stream) {
 *   console.log(`${event.type}:`, event.data);
 *
 *   if (event.type === 'debate_end') {
 *     break;
 *   }
 * }
 * ```
 *
 * @example
 * ```typescript
 * // Stream all events (no filter)
 * const stream = streamDebate({ baseUrl: 'http://localhost:8080' });
 *
 * for await (const event of stream) {
 *   console.log(event);
 * }
 * ```
 */
export async function* streamDebate(
  config: AragoraConfig,
  options: StreamOptions = {}
): AsyncGenerator<WebSocketEvent, void, unknown> {
  const ws = new AragoraWebSocket(config, options);
  const eventQueue: WebSocketEvent[] = [];
  let wakeNext: (() => void) | null = null;
  let ended = false;
  let terminalError: Error | null = null;
  let signalEnd: () => void;
  const terminalSignal = new Promise<void>((resolve) => {
    signalEnd = resolve;
  });
  const { debateId } = options;

  const wake = () => {
    if (ended) {
      signalEnd();
      // Let connect's onerror finish rejecting before disconnect changes its state.
      // Cleanup must not depend on when a paused consumer requests another event.
      queueMicrotask(() => {
        try {
          cleanup();
        } catch {
          terminalError ??= new ConnectionError('Failed to clean up WebSocket');
        }
      });
    }
    const notify = wakeNext;
    wakeNext = null;
    notify?.();
  };

  // Filter events by debate ID if specified
  const shouldEmit = (event: WebSocketEvent): boolean => {
    if (!debateId) {
      return true;
    }
    const eventDebateId = getEventDebateId(event);
    return !eventDebateId || eventDebateId === debateId;
  };

  // Handle incoming messages
  const unsubMessage = ws.on('message', (event) => {
    if (ended || !shouldEmit(event)) {
      return;
    }

    eventQueue.push(event);

    // Check for terminal events
    if (event.type === 'debate_end' || event.type === 'error') {
      ended = true;
    }
    wake();
  });

  // Handle errors
  const unsubError = ws.on('error', (error) => {
    if (ended) return;
    // A transport error commonly precedes close; type it immediately rather than
    // waiting for a close callback that cleanup may already have detached.
    // Low-level parse errors can contain raw frames, so do not copy their text.
    terminalError = error instanceof ConnectionError
      ? error
      : new ConnectionError('WebSocket stream failed');
    ended = true;
    wake();
  });

  // Handle disconnection
  const unsubDisconnect = ws.on('disconnected', ({ code }) => {
    if (ended) return;
    terminalError = new ConnectionError(
      'WebSocket disconnected before a terminal debate event',
      undefined,
      undefined,
      { code }
    );
    ended = true;
    wake();
  });

  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    unsubMessage();
    unsubError();
    unsubDisconnect();
    wakeNext = null;
    ws.disconnect();
  };

  try {
    // Setup failures need the same cleanup as iterator termination.
    // A close-before-open need not reject the low-level connection promise.
    await Promise.race([ws.connect(debateId), terminalSignal]);
    while (true) {
      if (eventQueue.length > 0) {
        yield eventQueue.shift()!;
      } else if (ended) {
        if (terminalError) throw terminalError;
        return;
      } else {
        await new Promise<void>((resolve) => {
          wakeNext = resolve;
        });
      }
    }
  } finally {
    cleanup();
  }
}

/**
 * Create a stream that automatically connects and yields events for a specific debate.
 *
 * This is a convenience wrapper around streamDebate that connects to a specific debate.
 *
 * @param config - Aragora configuration
 * @param debateId - The debate ID to stream events for
 * @param options - Additional WebSocket options
 * @returns AsyncGenerator yielding events for the specified debate
 *
 * @example
 * ```typescript
 * const config = { baseUrl: 'http://localhost:8080' };
 * const stream = streamDebateById(config, 'debate-123');
 *
 * for await (const event of stream) {
 *   if (event.type === 'agent_message') {
 *     console.log(`${event.data.agent}: ${event.data.content}`);
 *   }
 * }
 * ```
 */
export function streamDebateById(
  config: AragoraConfig,
  debateId: string,
  options?: WebSocketOptions
): AsyncGenerator<WebSocketEvent, void, unknown> {
  return streamDebate(config, { ...options, debateId });
}
