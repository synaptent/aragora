/**
 * Connectors API
 *
 * Handles connector management, integration configuration, sync operations,
 * and external platform integrations (Zapier, Make, n8n).
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export type ConnectorType =
  | 'github'
  | 's3'
  | 'sharepoint'
  | 'postgresql'
  | 'mongodb'
  | 'confluence'
  | 'notion'
  | 'slack'
  | 'fhir'
  | 'gdrive'
  | 'docusign'
  | 'pagerduty'
  | 'plaid'
  | 'qbo'
  | 'gusto';

export type IntegrationType =
  'slack' | 'discord' | 'telegram' | 'email' | 'teams' | 'whatsapp' | 'matrix';

export interface Connector {
  id: string;
  type: ConnectorType;
  name: string;
  status: 'active' | 'inactive' | 'error' | 'syncing';
  config: Record<string, unknown>;
  last_sync?: string;
  created_at: string;
  updated_at?: string;
}

export interface ConnectorCreateRequest {
  type: ConnectorType;
  name: string;
  config: Record<string, unknown>;
  schedule?: SyncSchedule;
}

export interface ConnectorUpdateRequest {
  name?: string;
  config?: Record<string, unknown>;
  schedule?: SyncSchedule;
}

export interface SyncSchedule {
  enabled: boolean;
  interval_minutes?: number;
  cron?: string;
}

export interface SyncOperation {
  id: string;
  connector_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: string;
  completed_at?: string;
  records_synced?: number;
  error?: string;
}

export interface SyncHistoryParams {
  connector_id?: string;
  status?: SyncOperation['status'];
  limit?: number;
  offset?: number;
}

export interface ConnectorStats {
  total_connectors: number;
  active_connectors: number;
  total_syncs: number;
  syncs_last_24h: number;
  records_synced_total: number;
  avg_sync_duration_ms: number;
}

export interface ConnectorHealth {
  connector_id: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  last_check: string;
  details?: Record<string, unknown>;
}

export interface ConnectorTypeInfo {
  type: ConnectorType;
  name: string;
  description: string;
  status: 'available' | 'coming_soon';
  required_config: string[];
}

export interface TestConnectionResult {
  success: boolean;
  message: string;
  latency_ms?: number;
  details?: Record<string, unknown>;
}

export interface Integration {
  type: IntegrationType;
  enabled: boolean;
  status: 'connected' | 'disconnected' | 'error';
  config?: Record<string, unknown>;
  last_activity?: string;
}

export interface IntegrationStats {
  total: number;
  connected: number;
  messages_last_24h: number;
}

// =============================================================================
// Connectors API Class
// =============================================================================

export class ConnectorsAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  // ===========================================================================
  // Connector CRUD
  // ===========================================================================

  /**
   * List all configured connectors
   */
  async list(): Promise<Connector[]> {
    return this.http.get('/api/v1/connectors');
  }

  /**
   * Get connector details by ID
   */
  async get(connectorId: string): Promise<Connector> {
    return this.http.get(`/api/v1/connectors/${connectorId}`);
  }

  /**
   * Configure a new connector
   */
  async create(data: ConnectorCreateRequest): Promise<Connector> {
    return this.http.post('/api/v1/connectors', data);
  }

  /**
   * Update connector configuration
   */
  async update(connectorId: string, data: ConnectorUpdateRequest): Promise<Connector> {
    return this.http.put(`/api/v1/connectors/${connectorId}`, data);
  }

  /**
   * Remove a connector
   */
  async delete(connectorId: string): Promise<void> {
    return this.http.delete(`/api/v1/connectors/${connectorId}`);
  }

  // ===========================================================================
  // Sync Operations
  // ===========================================================================

  /**
   * Start a sync operation for a connector
   */
  async startSync(connectorId: string, fullSync?: boolean): Promise<SyncOperation> {
    return this.http.post(`/api/v1/connectors/${connectorId}/sync`, { full_sync: fullSync });
  }

  /**
   * Cancel a running sync operation
   */
  async cancelSync(syncId: string): Promise<void> {
    return this.http.post(`/api/v1/connectors/sync/${syncId}/cancel`, {});
  }

  /**
   * Get sync history
   */
  async syncHistory(params?: SyncHistoryParams): Promise<SyncOperation[]> {
    const searchParams = new URLSearchParams();
    if (params?.connector_id) searchParams.set('connector_id', params.connector_id);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.offset) searchParams.set('offset', params.offset.toString());

    const query = searchParams.toString();
    return this.http.get(`/api/v1/connectors/sync-history${query ? `?${query}` : ''}`);
  }

  // ===========================================================================
  // Testing & Health
  // ===========================================================================

  /**
   * Test a connector configuration without saving
   */
  async testConnection(
    type: ConnectorType,
    config: Record<string, unknown>,
  ): Promise<TestConnectionResult> {
    return this.http.post('/api/v1/connectors/test', { type, config });
  }

  /**
   * Get health scores for all connectors
   */
  async health(): Promise<ConnectorHealth[]> {
    return this.http.get('/api/v1/connectors/health');
  }

  /**
   * Get aggregate connector statistics
   */
  async stats(): Promise<ConnectorStats> {
    return this.http.get('/api/v1/connectors/stats');
  }

  /**
   * List available connector types
   */
  async types(): Promise<ConnectorTypeInfo[]> {
    return this.http.get('/api/v1/connectors/types');
  }

  // ===========================================================================
  // Chat/Platform Integrations
  // ===========================================================================

  /**
   * List all chat platform integrations
   */
  async listIntegrations(): Promise<Integration[]> {
    return this.http.get('/api/v1/integrations');
  }

  /**
   * Get a specific integration by type
   */
  async getIntegration(type: IntegrationType): Promise<Integration> {
    return this.http.get(`/api/v1/integrations/${type}`);
  }

  /**
   * Configure a chat platform integration
   */
  async configureIntegration(
    type: IntegrationType,
    config: Record<string, unknown>,
  ): Promise<Integration> {
    return this.http.put(`/api/v1/integrations/${type}`, config);
  }

  /**
   * Enable or disable an integration
   */
  async toggleIntegration(type: IntegrationType, enabled: boolean): Promise<Integration> {
    return this.http.patch(`/api/v1/integrations/${type}`, { enabled });
  }

  /**
   * Test an integration connection
   */
  async testIntegration(type: IntegrationType): Promise<TestConnectionResult> {
    return this.http.post(`/api/v1/integrations/${type}/test`, {});
  }

  /**
   * Delete an integration
   */
  async deleteIntegration(type: IntegrationType): Promise<void> {
    return this.http.delete(`/api/v1/integrations/${type}`);
  }

  /**
   * Get integration statistics
   */
  async integrationStats(): Promise<IntegrationStats> {
    return this.http.get('/api/v1/integrations/status');
  }
}
