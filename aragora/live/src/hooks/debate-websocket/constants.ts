/**
 * Constants for Debate WebSocket hook
 */

import { WS_URL } from '@/config';

// Use centralized WS_URL from config (already handles env var with fallback)
export const DEFAULT_WS_URL = WS_URL;

// Timeout for waiting for debate_start event
// Increased to 180s for slow models like DeepSeek R1 which can take 90-120s for initial response
// Configurable via env var for deployments with faster/slower backends
export const DEBATE_START_TIMEOUT_MS = parseInt(
  process.env.NEXT_PUBLIC_WS_DEBATE_TIMEOUT || '180000',
  10,
); // 180 seconds (3 minutes)

// Activity timeout - how long to wait without any events before considering connection dead
export const DEBATE_ACTIVITY_TIMEOUT_MS = 300000; // 5 minutes (increased for slow models)

// Reconnection configuration
export const MAX_RECONNECT_ATTEMPTS = 15;
export const MAX_RECONNECT_DELAY_MS = 30000; // 30 seconds cap

// Orphaned stream cleanup - handles agents that never send token_end
// Reduced from 300s to 60s to clean up orphaned streams faster and reduce blank periods
// The proposal staggering fix prevents most orphaned streams by avoiding API rate limit bursts
export const STREAM_TIMEOUT_MS = 60000; // 60 seconds

// Stall detection - warn if no events received for 2 minutes during streaming
export const STALL_WARNING_MS = 120000; // 2 minutes

// Stream events buffer limit to prevent unbounded memory growth
export const MAX_STREAM_EVENTS = 500;

// Polling fallback interval (ms) when WebSocket is permanently unavailable
export const POLLING_INTERVAL_MS = parseInt(
  process.env.NEXT_PUBLIC_WS_POLLING_INTERVAL || '3000',
  10,
); // 3 seconds

// Heartbeat monitoring - if no heartbeat/event in this window, trigger
// proactive reconnect (should be > server heartbeat interval of 15s)
export const HEARTBEAT_TIMEOUT_MS = 45000; // 45 seconds
