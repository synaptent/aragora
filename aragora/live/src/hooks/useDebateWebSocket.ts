'use client';

/**
 * Debate WebSocket Hook - Re-exports for backwards compatibility
 *
 * This file re-exports from the modularized debate-websocket directory.
 * Import directly from '@/hooks/debate-websocket' for explicit imports.
 */

// Re-export everything from the modular location
export { useDebateWebSocket, default as default } from './debate-websocket';

export type {
  TranscriptMessage,
  StreamingMessage,
  DebateConnectionStatus,
  UseDebateWebSocketOptions,
  UseDebateWebSocketReturn,
  DebateStatus,
  EventData,
  ParsedEvent,
  SettlementMetadata,
} from './debate-websocket';

// Re-export constants for consumers that need them
export {
  DEFAULT_WS_URL,
  DEBATE_START_TIMEOUT_MS,
  DEBATE_ACTIVITY_TIMEOUT_MS,
  MAX_RECONNECT_ATTEMPTS,
  MAX_RECONNECT_DELAY_MS,
  STREAM_TIMEOUT_MS,
  STALL_WARNING_MS,
  MAX_STREAM_EVENTS,
} from './debate-websocket';

// Re-export utilities
export { makeStreamingKey, calculateReconnectDelay, isRetryableError } from './debate-websocket';
