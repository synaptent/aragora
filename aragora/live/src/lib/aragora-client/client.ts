/**
 * Aragora SDK Client (Modular)
 *
 * Unified client that provides access to all API modules.
 * This is the recommended entry point for the SDK.
 *
 * Usage:
 * ```typescript
 * import { createClient } from '@/lib/aragora-client/client';
 *
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'xxx' });
 *
 * // Access API modules
 * const debates = await client.debates.list();
 * const agents = await client.agents.list();
 * const health = await client.health();
 *
 * // WebSocket streaming
 * await client.ws.connect();
 * client.ws.subscribe('debate-123');
 * client.ws.on('agent_message', (event) => console.log(event));
 * ```
 */

import { HttpClient, AragoraClientConfig, AragoraError } from './apis/base';
import { DebatesAPI } from './apis/debates';
import { AgentsAPI } from './apis/agents';
import { AnalyticsAPI } from './apis/analytics';
import { WorkflowsAPI } from './apis/workflows';
import { AdminAPI } from './apis/admin';
import { TrainingAPI } from './apis/training';
import { ControlPlaneAPI } from './apis/control-plane';
import { GraphDebatesAPI } from './apis/graph-debates';
import { AuditAPI } from './apis/audit';
import { KnowledgeAPI } from './apis/knowledge';
import { ConnectorsAPI } from './apis/connectors';
import { AragoraWebSocket, createWebSocket, WebSocketOptions } from './apis/websocket';

// =============================================================================
// Client Configuration
// =============================================================================

export interface ClientConfig extends AragoraClientConfig {
  /** WebSocket URL (defaults to baseUrl with ws:// protocol) */
  wsUrl?: string;
}

// =============================================================================
// Unified Client
// =============================================================================

export class AragoraClient {
  private http: HttpClient;
  private _ws: AragoraWebSocket | null = null;
  private wsOptions: WebSocketOptions;

  // API Modules
  readonly debates: DebatesAPI;
  readonly agents: AgentsAPI;
  readonly analytics: AnalyticsAPI;
  readonly workflows: WorkflowsAPI;
  readonly admin: AdminAPI;
  readonly training: TrainingAPI;
  readonly controlPlane: ControlPlaneAPI;
  readonly graphDebates: GraphDebatesAPI;
  readonly audit: AuditAPI;
  readonly knowledge: KnowledgeAPI;
  readonly connectors: ConnectorsAPI;

  constructor(config: ClientConfig) {
    this.http = new HttpClient(config);

    // Initialize API modules
    this.debates = new DebatesAPI(this.http);
    this.agents = new AgentsAPI(this.http);
    this.analytics = new AnalyticsAPI(this.http);
    this.workflows = new WorkflowsAPI(this.http);
    this.admin = new AdminAPI(this.http);
    this.training = new TrainingAPI(this.http);
    this.controlPlane = new ControlPlaneAPI(this.http);
    this.graphDebates = new GraphDebatesAPI(this.http);
    this.audit = new AuditAPI(this.http);
    this.knowledge = new KnowledgeAPI(this.http);
    this.connectors = new ConnectorsAPI(this.http);

    // Store WebSocket options for lazy initialization
    this.wsOptions = {
      wsUrl: config.wsUrl || config.baseUrl.replace(/^http/, 'ws') + '/ws',
      apiKey: config.apiKey,
    };
  }

  /**
   * Get WebSocket client (lazy initialized)
   */
  get ws(): AragoraWebSocket {
    if (!this._ws) {
      this._ws = createWebSocket(this.wsOptions);
    }
    return this._ws;
  }

  // ==========================================================================
  // Health & System
  // ==========================================================================

  /**
   * Health check
   */
  async health(): Promise<{ status: string; version?: string }> {
    return this.http.get('/health');
  }

  /**
   * Readiness check
   */
  async ready(): Promise<{ ready: boolean; checks: Record<string, boolean> }> {
    return this.http.get('/health/ready');
  }

  /**
   * Get API version
   */
  async version(): Promise<{ version: string; build?: string }> {
    return this.http.get('/api/version');
  }

  // ==========================================================================
  // User & Auth (convenience methods)
  // ==========================================================================

  /**
   * Get current user profile
   */
  async me(): Promise<unknown> {
    return this.http.get('/api/users/me');
  }

  /**
   * Update current user profile
   */
  async updateProfile(updates: Record<string, unknown>): Promise<unknown> {
    return this.http.patch('/api/users/me', updates);
  }

  // ==========================================================================
  // Cleanup
  // ==========================================================================

  /**
   * Disconnect WebSocket and cleanup resources
   */
  disconnect(): void {
    this._ws?.disconnect();
    this._ws = null;
  }
}

// =============================================================================
// Factory Functions
// =============================================================================

/**
 * Create a new Aragora client instance
 */
export function createClient(config: ClientConfig): AragoraClient {
  return new AragoraClient(config);
}

// Singleton instance for frontend usage
let _clientInstance: AragoraClient | null = null;

/**
 * Get or create a singleton client instance
 * Primarily for frontend usage with React context
 */
export function getClient(apiKey?: string, baseUrl?: string): AragoraClient {
  if (!_clientInstance || apiKey) {
    _clientInstance = createClient({
      baseUrl: baseUrl || process.env.NEXT_PUBLIC_API_URL || 'https://api.aragora.ai',
      apiKey,
    });
  }
  return _clientInstance;
}

/**
 * Clear the singleton client instance
 */
export function clearClient(): void {
  _clientInstance?.disconnect();
  _clientInstance = null;
}

// =============================================================================
// Re-exports
// =============================================================================

export { AragoraError };

// Re-export types from modules
export type {
  Debate,
  DebateMessage,
  DebateRound,
  DebateCreateRequest,
  DebateCreateResponse,
  ConsensusResult,
} from './apis/debates';

export type { AgentProfile, LeaderboardEntry } from './apis/agents';

export type { Workflow, WorkflowTemplate, WorkflowExecution } from './apis/workflows';

export type { WebSocketState, DebateEvent } from './apis/websocket';

export type {
  RevenueData,
  RevenueResponse,
  AdminStats,
  AdminStatsResponse,
  Organization,
  User,
} from './apis/admin';

export type {
  TrainingStats,
  TrainingStatsResponse,
  SFTExample,
  DPOExample,
  GauntletExample,
  TrainingExportOptions,
  TrainingExportResponse,
  TrainingJob,
} from './apis/training';

export type {
  Agent,
  AgentRegistration,
  Task,
  TaskSubmission,
  Deliberation,
  SystemHealth as ControlPlaneHealth,
  ControlPlaneStats,
  PolicyViolation,
} from './apis/control-plane';

export type {
  GraphDebateRequest,
  GraphDebateResponse,
  GraphNode,
  Branch,
  DebateGraph,
} from './apis/graph-debates';

export type {
  AuditSession,
  Finding,
  AuditEvent,
  AuditReport,
  DeepAuditRequest,
  DeepAuditResponse,
} from './apis/audit';

export type {
  KnowledgeNode,
  Relationship,
  QueryOptions,
  QueryResponse,
  MoundStats,
} from './apis/knowledge';

export type { Connector, ConnectorType, SyncOperation, Integration } from './apis/connectors';
