/**
 * Types for event handler context and shared interfaces
 */

import type { StreamEvent } from '@/types/events';
import type {
  TranscriptMessage,
  StreamingMessage,
  DebateConnectionStatus,
  ConnectionQuality,
  SettlementMetadata,
} from '../types';

/**
 * Context provided to all event handlers for state access
 */
export interface EventHandlerContext {
  debateId: string;

  // State setters
  setTask: React.Dispatch<React.SetStateAction<string>>;
  setAgents: React.Dispatch<React.SetStateAction<string[]>>;
  setDebateMode: React.Dispatch<React.SetStateAction<string | null>>;
  setSettlementMetadata: React.Dispatch<React.SetStateAction<SettlementMetadata | null>>;
  setStatus: React.Dispatch<React.SetStateAction<DebateConnectionStatus>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
  setErrorDetails: React.Dispatch<React.SetStateAction<string | null>>;
  setHasCitations: React.Dispatch<React.SetStateAction<boolean>>;
  setHasReceivedDebateStart: React.Dispatch<React.SetStateAction<boolean>>;
  setStreamingMessages: React.Dispatch<React.SetStateAction<Map<string, StreamingMessage>>>;

  // Helper functions
  addMessageIfNew: (msg: TranscriptMessage) => boolean;
  addStreamEvent: (event: StreamEvent) => void;
  clearDebateStartTimeout: () => void;
  setConnectionQuality: React.Dispatch<React.SetStateAction<ConnectionQuality | null>>;

  // Refs for callbacks
  errorCallbackRef: React.MutableRefObject<((message: string) => void) | null>;
  ackCallbackRef: React.MutableRefObject<((msgType: string) => void) | null>;
  seenMessagesRef: React.MutableRefObject<Set<string>>;
  lastSeqRef: React.MutableRefObject<number>;
  lastActivityRef: React.MutableRefObject<number>;

  // Auth callbacks
  onAuthRevoked?: () => void;
}

/**
 * Parsed event from WebSocket
 */
export interface ParsedEventData {
  type: string;
  agent?: string;
  seq?: number;
  agent_seq?: number;
  loop_id?: string;
  task_id?: string;
  round?: number;
  timestamp?: number;
  data?: Record<string, unknown>;
}

/**
 * Event handler function signature
 */
export type EventHandler = (data: ParsedEventData, ctx: EventHandlerContext) => void;

/**
 * Event handler registry mapping event types to handlers
 */
export type EventHandlerRegistry = Record<string, EventHandler>;
