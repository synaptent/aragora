/**
 * Debate WebSocket hook exports
 *
 * This module provides WebSocket-based real-time communication for debates.
 * It handles connection management, event processing, and state synchronization.
 */

// Re-export from main hook
export { useDebateWebSocket } from './useDebateWebSocket';
export { useDebateWebSocket as default } from './useDebateWebSocket';

// Re-export types
export type {
  TranscriptMessage,
  StreamingMessage,
  DebateConnectionStatus,
  UseDebateWebSocketOptions,
  UseDebateWebSocketReturn,
  DebateStatus,
  EventData,
  ParsedEvent,
  ConnectionQuality,
  SettlementMetadata,
} from './types';

// Re-export constants
export {
  DEFAULT_WS_URL,
  DEBATE_START_TIMEOUT_MS,
  DEBATE_ACTIVITY_TIMEOUT_MS,
  MAX_RECONNECT_ATTEMPTS,
  MAX_RECONNECT_DELAY_MS,
  STREAM_TIMEOUT_MS,
  STALL_WARNING_MS,
  MAX_STREAM_EVENTS,
  POLLING_INTERVAL_MS,
  HEARTBEAT_TIMEOUT_MS,
} from './constants';

// Re-export utilities
export { makeStreamingKey, calculateReconnectDelay, isRetryableError } from './utils';
