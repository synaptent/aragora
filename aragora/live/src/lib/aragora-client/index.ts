/**
 * Aragora SDK Client - Modular Export
 *
 * This module provides both:
 * 1. The new modular SDK structure (recommended)
 * 2. Backward compatibility with the legacy monolithic client
 *
 * Recommended Usage (new):
 * ```typescript
 * import { createClient, AragoraClient } from '@/lib/aragora-client';
 *
 * const client = createClient({ baseUrl: '...', apiKey: '...' });
 * const debates = await client.debates.list();
 * ```
 *
 * Legacy Usage (backward compatible):
 * ```typescript
 * import { getClient, useAragoraClient } from '@/lib/aragora-client';
 *
 * const client = getClient(token);
 * const debates = await client.debates.list();
 * ```
 *
 * Module Structure:
 * - apis/base.ts     - HttpClient and error handling
 * - apis/debates.ts  - Debates API
 * - apis/agents.ts   - Agents API
 * - apis/analytics.ts - Analytics API
 * - apis/workflows.ts - Workflows API
 * - apis/websocket.ts - WebSocket client
 * - client.ts        - Unified client
 */

// =============================================================================
// New Modular Exports (Recommended)
// =============================================================================

// Main client
export { AragoraClient, createClient, getClient, clearClient, AragoraError } from './client';

export type { ClientConfig } from './client';
export type { AragoraClientConfig } from './apis/base';

// API Modules (for direct imports if needed)
export { DebatesAPI } from './apis/debates';
export { AgentsAPI } from './apis/agents';
export { AnalyticsAPI } from './apis/analytics';
export { WorkflowsAPI } from './apis/workflows';
export { AragoraWebSocket, createWebSocket } from './apis/websocket';

// All types
export type {
  // Debates
  Debate,
  DebateMessage,
  DebateRound,
  DebateCreateRequest,
  DebateCreateResponse,
  DebateListParams,
  DebateListResponse,
  ConsensusResult,
} from './apis/debates';

export type {
  // Agents
  AgentProfile,
  AgentCreateRequest,
  LeaderboardEntry,
  LeaderboardResponse,
  AgentStatsResponse,
} from './apis/agents';

export type {
  // Analytics
  AnalyticsSummary,
  AnalyticsOverview,
  FindingsTrend,
  RemediationMetrics,
  AgentMetrics,
  CostAnalysis,
  ComplianceScore,
  HeatmapData,
  DisagreementStats,
} from './apis/analytics';

export type {
  // Workflows
  Workflow,
  WorkflowNode,
  WorkflowTemplate,
  WorkflowExecution,
  WorkflowCreateRequest,
} from './apis/workflows';

export type {
  // WebSocket
  WebSocketOptions,
  WebSocketState,
  DebateEvent,
  EventHandler,
  StateHandler,
  ErrorHandler,
} from './apis/websocket';

// =============================================================================
// Legacy Exports (Backward Compatibility)
// =============================================================================

// Re-export everything from the legacy monolithic client
// This ensures existing code continues to work
export * from '../aragora-client';
