/**
 * WebSocket Client for Aragora
 *
 * Provides real-time streaming of debate events and updates.
 */

import { logger } from '@/utils/logger';

// =============================================================================
// Types
// =============================================================================

export type WebSocketState = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface WebSocketOptions {
  wsUrl?: string;
  apiKey?: string;
  autoReconnect?: boolean;
  maxReconnectAttempts?: number;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
  maxHandshakeFailures?: number;
  heartbeatInterval?: number;
}

export interface DebateEvent {
  type:
    | 'debate_start'
    | 'round_start'
    | 'agent_message'
    | 'critique'
    | 'vote'
    | 'consensus'
    | 'debate_end'
    | 'error';
  debate_id: string;
  payload: unknown;
  timestamp: string;
}

export type EventHandler = (event: DebateEvent) => void;
export type StateHandler = (state: WebSocketState) => void;
export type ErrorHandler = (error: Error) => void;

// =============================================================================
// WebSocket Client
// =============================================================================

export class AragoraWebSocket {
  private ws: WebSocket | null = null;
  private options: Required<WebSocketOptions>;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private hasEverConnected = false;
  private handshakeFailures = 0;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private eventHandlers: Map<string, Set<EventHandler>> = new Map();
  private stateHandlers: Set<StateHandler> = new Set();
  private errorHandlers: Set<ErrorHandler> = new Set();
  private state: WebSocketState = 'disconnected';
  private subscribedDebates: Set<string> = new Set();

  constructor(options: WebSocketOptions) {
    this.options = {
      wsUrl: options.wsUrl || 'wss://api.aragora.ai/ws',
      apiKey: options.apiKey || '',
      autoReconnect: options.autoReconnect ?? true,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 5,
      reconnectDelay: options.reconnectDelay ?? 1000,
      maxReconnectDelay: options.maxReconnectDelay ?? 30000,
      maxHandshakeFailures: options.maxHandshakeFailures ?? 3,
      heartbeatInterval: options.heartbeatInterval ?? 30000,
    };
  }

  /**
   * Connect to the WebSocket server
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        resolve();
        return;
      }
      if (this.state === 'connecting') {
        return;
      }

      this.setState('connecting');

      const url = new URL(this.options.wsUrl);
      if (this.options.apiKey) {
        url.searchParams.set('token', this.options.apiKey);
      }

      this.ws = new WebSocket(url.toString());

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.hasEverConnected = true;
        this.handshakeFailures = 0;
        this.setState('connected');
        this.startHeartbeat();

        // Resubscribe to debates
        this.subscribedDebates.forEach((debateId) => {
          this.send({ type: 'subscribe', debate_id: debateId });
        });

        resolve();
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as DebateEvent;
          this.handleEvent(data);
        } catch (e) {
          logger.error('Failed to parse WebSocket message:', e);
        }
      };

      this.ws.onclose = () => {
        this.stopHeartbeat();
        this.setState('disconnected');

        if (!this.hasEverConnected) {
          this.handshakeFailures += 1;
          if (this.handshakeFailures >= this.options.maxHandshakeFailures) {
            this.setState('error');
            return;
          }
        }

        this.scheduleReconnect();
      };

      this.ws.onerror = (_error) => {
        this.setState('error');
        const err = new Error('WebSocket error');
        this.errorHandlers.forEach((handler) => handler(err));
        reject(err);
      };
    });
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    this.options.autoReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
    this.ws?.close();
    this.ws = null;
    this.setState('disconnected');
  }

  /**
   * Subscribe to debate events
   */
  subscribe(debateId: string): void {
    this.subscribedDebates.add(debateId);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: 'subscribe', debate_id: debateId });
    }
  }

  /**
   * Unsubscribe from debate events
   */
  unsubscribe(debateId: string): void {
    this.subscribedDebates.delete(debateId);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: 'unsubscribe', debate_id: debateId });
    }
  }

  /**
   * Add event handler for specific event type
   */
  on(eventType: string, handler: EventHandler): void {
    if (!this.eventHandlers.has(eventType)) {
      this.eventHandlers.set(eventType, new Set());
    }
    this.eventHandlers.get(eventType)!.add(handler);
  }

  /**
   * Remove event handler
   */
  off(eventType: string, handler: EventHandler): void {
    this.eventHandlers.get(eventType)?.delete(handler);
  }

  /**
   * Add state change handler
   */
  onStateChange(handler: StateHandler): void {
    this.stateHandlers.add(handler);
  }

  /**
   * Remove state change handler
   */
  offStateChange(handler: StateHandler): void {
    this.stateHandlers.delete(handler);
  }

  /**
   * Add error handler
   */
  onError(handler: ErrorHandler): void {
    this.errorHandlers.add(handler);
  }

  /**
   * Remove error handler
   */
  offError(handler: ErrorHandler): void {
    this.errorHandlers.delete(handler);
  }

  /**
   * Get current connection state
   */
  getState(): WebSocketState {
    return this.state;
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.state === 'connected' && this.ws?.readyState === WebSocket.OPEN;
  }

  // Private methods
  private send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private setState(state: WebSocketState): void {
    this.state = state;
    this.stateHandlers.forEach((handler) => handler(state));
  }

  private handleEvent(event: DebateEvent): void {
    // Call type-specific handlers
    this.eventHandlers.get(event.type)?.forEach((handler) => handler(event));

    // Call wildcard handlers
    this.eventHandlers.get('*')?.forEach((handler) => handler(event));
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'ping' });
    }, this.options.heartbeatInterval);
  }

  private scheduleReconnect(): void {
    if (!this.options.autoReconnect) {
      return;
    }
    if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      this.setState('error');
      return;
    }

    this.reconnectAttempts += 1;
    const baseDelay = this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    const delay = Math.min(baseDelay, this.options.maxReconnectDelay);
    const jitter = delay * (0.8 + Math.random() * 0.4);

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => this.connect(), jitter);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}

/**
 * Create a WebSocket client instance
 */
export function createWebSocket(options: WebSocketOptions): AragoraWebSocket {
  return new AragoraWebSocket(options);
}
