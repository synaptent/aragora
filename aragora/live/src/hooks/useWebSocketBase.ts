'use client';

/**
 * Base WebSocket hook with common connection management.
 *
 * Provides:
 * - Connection lifecycle management
 * - Automatic reconnection with exponential backoff
 * - Connection status tracking
 * - Event deduplication
 *
 * Domain-specific hooks (useDebateWebSocket, useGauntletWebSocket, etc.)
 * build on this foundation and add their own event processing.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { logger } from '@/utils/logger';

// Reconnection configuration (shared across all WebSocket hooks)
export const MAX_RECONNECT_ATTEMPTS = 15;
export const MAX_RECONNECT_DELAY_MS = 30000; // 30 seconds cap

export type WebSocketConnectionStatus =
  'disconnected' | 'connecting' | 'connected' | 'streaming' | 'complete' | 'error';

/**
 * Validate WebSocket URL format.
 */
export function validateWsUrl(url: string): { valid: boolean; error?: string } {
  if (!url) {
    return { valid: false, error: 'WebSocket URL is required' };
  }
  if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
    return { valid: false, error: 'Invalid WebSocket URL protocol (must be ws:// or wss://)' };
  }
  try {
    new URL(url);
  } catch {
    return { valid: false, error: 'Invalid WebSocket URL format' };
  }
  return { valid: true };
}

export interface WebSocketBaseOptions<TEvent = unknown> {
  /** WebSocket URL to connect to */
  wsUrl: string;

  /** Whether the connection is enabled */
  enabled?: boolean;

  /** Whether to automatically reconnect on disconnection */
  autoReconnect?: boolean;

  /** Message to send on connection open (e.g., subscription message) */
  subscribeMessage?: Record<string, unknown> | null;

  /** Callback when a message is received (parsed JSON) */
  onEvent?: (event: TEvent) => void;

  /** Callback when connection opens */
  onConnect?: () => void;

  /** Callback when connection closes */
  onDisconnect?: () => void;

  /** Callback for connection errors */
  onError?: (error: string) => void;

  /** Logger prefix for debugging */
  logPrefix?: string;
}

export interface WebSocketBaseReturn {
  /** Current connection status */
  status: WebSocketConnectionStatus;

  /** Error message if any */
  error: string | null;

  /** Whether WebSocket is currently connected */
  isConnected: boolean;

  /** Current reconnection attempt number (for UI feedback) */
  reconnectAttempt: number;

  /** Send a message through the WebSocket */
  send: (message: Record<string, unknown>) => void;

  /** Manually trigger reconnection */
  reconnect: () => void;

  /** Manually close the connection */
  disconnect: () => void;
}

/**
 * Base WebSocket hook for common connection management.
 *
 * @example
 * ```tsx
 * const { status, isConnected, send, reconnect } = useWebSocketBase({
 *   wsUrl: 'wss://api.example.com/ws',
 *   subscribeMessage: { type: 'subscribe', debate_id: debateId },
 *   onEvent: (event) => {
 *     // Process domain-specific events
 *   },
 *   logPrefix: '[Debate]',
 * });
 * ```
 */
export function useWebSocketBase<TEvent = unknown>({
  wsUrl,
  enabled = true,
  autoReconnect = true,
  subscribeMessage = null,
  onEvent,
  onConnect,
  onDisconnect,
  onError,
  logPrefix = '[WebSocket]',
}: WebSocketBaseOptions<TEvent>): WebSocketBaseReturn {
  const MAX_HANDSHAKE_FAILURES = 3;
  const [status, setStatus] = useState<WebSocketConnectionStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isUnmountedRef = useRef(false);
  const hasEverConnectedRef = useRef(false);
  const handshakeFailuresRef = useRef(0);

  // Track reconnect trigger to force reconnection
  const [reconnectTrigger, setReconnectTrigger] = useState(0);

  // Message deduplication
  const seenMessagesRef = useRef<Set<string>>(new Set());

  // Clear any pending reconnection timeout
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // Schedule reconnection with exponential backoff
  const scheduleReconnect = useCallback(() => {
    if (isUnmountedRef.current || !autoReconnect) return;
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      setStatus('error');
      setError(`Connection lost. Max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached.`);
      onError?.(`Max reconnection attempts reached`);
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped at MAX_RECONNECT_DELAY_MS)
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY_MS);
    logger.debug(`${logPrefix} Scheduling reconnect attempt ${reconnectAttempt + 1} in ${delay}ms`);

    clearReconnectTimeout();
    reconnectTimeoutRef.current = setTimeout(() => {
      if (!isUnmountedRef.current) {
        setReconnectAttempt((prev) => prev + 1);
        setReconnectTrigger((prev) => prev + 1);
      }
    }, delay);
  }, [reconnectAttempt, autoReconnect, clearReconnectTimeout, logPrefix, onError]);

  // Send message through WebSocket
  const send = useCallback(
    (message: Record<string, unknown>) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(message));
        logger.debug(`${logPrefix} Sent:`, message);
      } else {
        logger.warn(`${logPrefix} Cannot send message - WebSocket not open`);
      }
    },
    [logPrefix],
  );

  // Manual reconnect trigger
  const reconnect = useCallback(() => {
    setReconnectAttempt(0);
    setError(null);
    hasEverConnectedRef.current = false;
    handshakeFailuresRef.current = 0;
    setReconnectTrigger((prev) => prev + 1);
  }, []);

  // Manual disconnect
  const disconnect = useCallback(() => {
    clearReconnectTimeout();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus('disconnected');
  }, [clearReconnectTimeout]);

  // Main connection effect
  useEffect(() => {
    if (!enabled) {
      disconnect();
      return;
    }

    // Validate URL
    const validation = validateWsUrl(wsUrl);
    if (!validation.valid) {
      setStatus('error');
      setError(validation.error || 'Invalid WebSocket URL');
      return;
    }

    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    isUnmountedRef.current = false;
    seenMessagesRef.current.clear();

    try {
      const url = wsUrl.endsWith('/') ? wsUrl.slice(0, -1) : wsUrl;
      logger.debug(`${logPrefix} Connecting to: ${url}`);

      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus('connecting');
      setError(null);

      ws.onopen = () => {
        if (isUnmountedRef.current) return;

        logger.debug(`${logPrefix} Connected (attempt ${reconnectAttempt + 1})`);
        setStatus('connected');
        setReconnectAttempt(0);
        hasEverConnectedRef.current = true;
        handshakeFailuresRef.current = 0;
        clearReconnectTimeout();

        // Send subscription message if provided
        if (subscribeMessage) {
          ws.send(JSON.stringify(subscribeMessage));
          logger.debug(`${logPrefix} Sent subscription:`, subscribeMessage);
        }

        onConnect?.();
      };

      ws.onclose = (event) => {
        if (isUnmountedRef.current) return;

        logger.debug(`${logPrefix} Connection closed: code=${event.code}, reason=${event.reason}`);

        // Normal closure
        if (event.code === 1000) {
          setStatus('disconnected');
          onDisconnect?.();
          return;
        }

        if (!hasEverConnectedRef.current) {
          handshakeFailuresRef.current += 1;
          if (handshakeFailuresRef.current >= MAX_HANDSHAKE_FAILURES) {
            setStatus('error');
            setError('WebSocket unavailable');
            onError?.('WebSocket unavailable');
            onDisconnect?.();
            return;
          }
        }

        scheduleReconnect();
        onDisconnect?.();
      };

      ws.onerror = (event) => {
        if (isUnmountedRef.current) return;

        logger.error(`${logPrefix} Error:`, event);
        const errorMsg = 'WebSocket connection error';
        setError(errorMsg);
        onError?.(errorMsg);
      };

      ws.onmessage = (event) => {
        if (isUnmountedRef.current) return;

        try {
          const data = JSON.parse(event.data);

          // Deduplication using seq if available
          if (data.seq !== undefined) {
            const key = `${data.type}:${data.seq}`;
            if (seenMessagesRef.current.has(key)) {
              return;
            }
            seenMessagesRef.current.add(key);

            // Prevent unbounded memory growth
            if (seenMessagesRef.current.size > 10000) {
              const entries = Array.from(seenMessagesRef.current);
              seenMessagesRef.current = new Set(entries.slice(-5000));
            }
          }

          // Call domain-specific event handler
          onEvent?.(data as TEvent);
        } catch (e) {
          logger.warn(`${logPrefix} Failed to parse message:`, e);
        }
      };
    } catch (e) {
      logger.error(`${logPrefix} Failed to create WebSocket:`, e);
      setStatus('error');
      setError('Failed to create WebSocket connection');
      scheduleReconnect();
    }

    // Cleanup on unmount or dependency change
    return () => {
      isUnmountedRef.current = true;
      clearReconnectTimeout();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [
    wsUrl,
    enabled,
    reconnectTrigger,
    subscribeMessage,
    logPrefix,
    onEvent,
    onConnect,
    onDisconnect,
    onError,
    clearReconnectTimeout,
    scheduleReconnect,
    reconnectAttempt,
    disconnect,
  ]);

  const isConnected = status === 'connected' || status === 'streaming';

  return { status, error, isConnected, reconnectAttempt, send, reconnect, disconnect };
}

export default useWebSocketBase;
