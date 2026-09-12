/**
 * Types for Debate WebSocket hook
 */

import type { StreamEvent } from '@/types/events';

export interface SettlementMetadata {
  claim?: string;
  falsifier?: string;
  metric?: string;
  review_horizon_days?: number;
  resolver_type?: string;
  status?: string;
  next_review_at?: string | null;
  sla_state?: string;
  sla_reason?: string;
}

export interface TranscriptMessage {
  agent: string;
  role?: string;
  content: string;
  round?: number;
  phase?: number; // Current debate phase (0-8 for 9-round format)
  timestamp?: number;
  calibration?: {
    brier_score: number;
    ece: number;
    trust_tier: 'excellent' | 'good' | 'moderate' | 'poor' | 'unrated';
    prediction_count: number;
  } | null;
  // Reasoning visibility fields (from agent_message events)
  confidence_score?: number | null;
  reasoning_phase?: string;
  thinking?: string;
}

export interface ReasoningStep {
  thinking: string;
  timestamp: number;
  step?: number;
}

export interface EvidenceSource {
  title: string;
  url?: string;
  relevance?: number;
}

export interface StreamingMessage {
  agent: string;
  taskId: string; // Task ID for distinguishing concurrent outputs from same agent
  content: string;
  isComplete: boolean;
  startTime: number;
  expectedSeq: number; // Next expected agent_seq for ordering
  pendingTokens: Map<number, string>; // Buffer for out-of-order tokens
  // Reasoning visibility
  reasoning: ReasoningStep[];
  evidence: EvidenceSource[];
  confidence: number | null;
  reasoningPhase: string; // Current reasoning phase (e.g. "ANALYZING", "FORMING ARGUMENT")
}

export type DebateConnectionStatus =
  'idle' | 'connecting' | 'streaming' | 'polling' | 'complete' | 'error';

export interface UseDebateWebSocketOptions {
  debateId: string;
  wsUrl?: string;
  enabled?: boolean;
  /** Access token for WebSocket authentication */
  accessToken?: string | null;
  /** Callback when authentication is revoked (token expired/invalid) */
  onAuthRevoked?: () => void;
}

/** Connection quality metrics reported by the server heartbeat. */
export interface ConnectionQuality {
  reconnectCount: number;
  avgLatencyMs: number;
  uptimeSeconds: number;
  lastSeq: number;
  bufferSize: number;
  oldestSeq: number;
}

export interface UseDebateWebSocketReturn {
  // Connection state
  status: DebateConnectionStatus;
  error: string | null;
  errorDetails: string | null; // Detailed error message from server
  isConnected: boolean;
  isPolling: boolean;
  reconnectAttempt: number; // Expose for UI feedback
  connectionQuality: ConnectionQuality | null; // Server-reported quality metrics

  // Debate data
  task: string;
  agents: string[];
  debateMode: string | null;
  settlement: SettlementMetadata | null;
  messages: TranscriptMessage[];
  streamingMessages: Map<string, StreamingMessage>;
  streamEvents: StreamEvent[];
  hasCitations: boolean;

  // Actions
  sendVote: (choice: string, intensity?: number) => void;
  sendSuggestion: (suggestion: string) => void;
  registerAckCallback: (callback: (msgType: string) => void) => () => void;
  registerErrorCallback: (callback: (message: string) => void) => () => void;
  reconnect: () => void; // Manual reconnect trigger
  sendPing: () => void; // Application-level latency measurement ping
}

// Debate status from server API
export interface DebateStatus {
  status: string;
  error?: string;
  task?: string;
  agents?: string[];
  mode?: string | null;
  settlement?: SettlementMetadata | null;
}

// Event data types for type-safe event processing
export interface EventData {
  debate_id?: string;
  loop_id?: string;
  task?: string;
  agents?: string[];
  agent?: string;
  content?: string;
  token?: string;
  issues?: string[];
  target?: string;
  confidence?: number;
  round?: number;
  phase?: number;
  mode?: string;
  settlement?: SettlementMetadata;
  timestamp?: number;
  error_type?: string;
  message?: string;
  dropped_count?: number;
  ended?: boolean;
  messages?: Array<Record<string, unknown>>;
}

export interface ParsedEvent {
  type: string;
  agent?: string;
  seq?: number;
  loop_id?: string;
  task_id?: string;
  round?: number;
  timestamp?: number;
  data?: EventData;
}
