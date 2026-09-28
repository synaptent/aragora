/**
 * Connectors Namespace API
 *
 * Provides methods for managing enterprise data source connectors,
 * sync operations, and scheduler configuration.
 *
 * Features:
 * - Connector management (GitHub Enterprise, S3, PostgreSQL, MongoDB, FHIR)
 * - Sync scheduling and monitoring
 * - Connector health checks
 */

/**
 * Supported connector types.
 */
export type ConnectorType = 'github_enterprise' | 's3' | 'postgresql' | 'mongodb' | 'fhir';

/**
 * Sync frequency options.
 */
export type SyncFrequency = 'hourly' | 'daily' | 'weekly' | 'manual';

/**
 * Sync operation status.
 */
export type SyncStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

/**
 * Connector health status.
 */
export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

/**
 * Connector details.
 */
export interface Connector {
  id: string;
  name: string;
  type: ConnectorType;
  config: Record<string, unknown>;
  schedule: SyncFrequency;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_sync_at?: string;
  health_status: HealthStatus;
}

/**
 * Sync operation details.
 */
export interface SyncOperation {
  sync_id: string;
  connector_id: string;
  status: SyncStatus;
  full_sync: boolean;
  started_at: string;
  completed_at?: string;
  records_processed?: number;
  records_failed?: number;
  error_message?: string;
  progress_percent?: number;
}

/**
 * Connection test result.
 */
export interface ConnectionTestResult {
  connection_ok: boolean;
  latency_ms: number;
  error_message?: string;
  tested_at: string;
}

/**
 * Connector health details.
 */
export interface ConnectorHealth {
  connector_id: string;
  status: HealthStatus;
  last_sync_at?: string;
  last_sync_status?: SyncStatus;
  error_count_24h: number;
  avg_sync_duration_ms?: number;
  last_error?: string;
  checked_at: string;
}

/**
 * Pagination info.
 */
export interface PaginationInfo {
  limit: number;
  offset: number;
  total: number;
  has_more: boolean;
}

/**
 * Client interface for connectors operations.
 */
interface ConnectorsClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Connectors API for managing enterprise data source integrations.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // List all connectors
 * const { connectors } = await client.connectors.list();
 *
 * // Create a new connector
 * const connector = await client.connectors.create(
 *   'my-postgres',
 *   'postgresql',
 *   { host: 'db.example.com', database: 'mydb' }
 * );
 *
 * // Trigger a sync
 * const sync = await client.connectors.triggerSync(connector.id);
 * ```
 */
export class ConnectorsAPI {
  constructor(private client: ConnectorsClientInterface) {}

  // ===========================================================================
  // Connector Management
  // ===========================================================================

  /**
   * List configured connectors with filtering and pagination.
   *
   * @param options - List options
   * @param options.connectorType - Filter by connector type
   * @param options.limit - Maximum number of results (default: 50)
   * @param options.offset - Pagination offset (default: 0)
   */
  async list(options?: {
    connectorType?: ConnectorType;
    limit?: number;
    offset?: number;
  }): Promise<{
    connectors: Connector[];
    pagination: PaginationInfo;
  }> {
    const params: Record<string, unknown> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    if (options?.connectorType) {
      params.type = options.connectorType;
    }

    return this.client.request('GET', '/api/v1/connectors', { params });
  }

  /**
   * Get a connector by ID.
   *
   * @param connectorId - Connector ID
   */
  async get(connectorId: string): Promise<Connector> {
    return this.client.request('GET', `/api/v1/connectors/${connectorId}`);
  }

  /**
   * Create a new connector.
   *
   * @param name - Connector name
   * @param connectorType - Type of connector
   * @param config - Connector-specific configuration
   * @param schedule - Sync frequency (default: 'daily')
   */
  async create(
    name: string,
    connectorType: ConnectorType,
    config: Record<string, unknown>,
    schedule: SyncFrequency = 'daily'
  ): Promise<Connector> {
    return this.client.request('POST', '/api/v1/connectors', {
      json: {
        name,
        type: connectorType,
        config,
        schedule,
      },
    });
  }

  /**
   * Update a connector.
   *
   * @param connectorId - Connector ID
   * @param options - Update options
   * @param options.name - New name
   * @param options.config - New configuration
   * @param options.schedule - New sync frequency
   * @param options.enabled - Enable/disable connector
   */
  async update(
    connectorId: string,
    options?: {
      name?: string;
      config?: Record<string, unknown>;
      schedule?: SyncFrequency;
      enabled?: boolean;
    }
  ): Promise<Connector> {
    const data: Record<string, unknown> = {};
    if (options?.name !== undefined) {
      data.name = options.name;
    }
    if (options?.config !== undefined) {
      data.config = options.config;
    }
    if (options?.schedule !== undefined) {
      data.schedule = options.schedule;
    }
    if (options?.enabled !== undefined) {
      data.enabled = options.enabled;
    }

    return this.client.request('PATCH', `/api/v1/connectors/${connectorId}`, { json: data });
  }

  /**
   * Delete a connector.
   *
   * @param connectorId - Connector ID
   */
  async delete(connectorId: string): Promise<{ deleted: boolean; message: string }> {
    return this.client.request('DELETE', `/api/v1/connectors/${connectorId}`);
  }

  // ===========================================================================
  // Sync Operations
  // ===========================================================================

  /**
   * Trigger a sync for a connector.
   *
   * @param connectorId - Connector ID
   * @param fullSync - Whether to do a full sync instead of incremental (default: false)
   */
  async triggerSync(
    connectorId: string,
    fullSync = false
  ): Promise<{ sync_id: string; status: SyncStatus; message: string }> {
    return this.client.request('POST', `/api/v1/connectors/${connectorId}/sync`, {
      json: { full_sync: fullSync },
    });
  }

  /**
   * Get status of a sync operation.
   *
   * @param connectorId - Connector ID
   * @param syncId - Sync operation ID
   */
  async getSyncStatus(connectorId: string, syncId: string): Promise<SyncOperation> {
    return this.client.request('GET', `/api/v1/connectors/${connectorId}/syncs/${syncId}`);
  }

  /**
   * List recent sync operations for a connector.
   *
   * @param connectorId - Connector ID
   * @param limit - Maximum number of results (default: 20)
   */
  async listSyncs(
    connectorId: string,
    limit = 20
  ): Promise<{ syncs: SyncOperation[]; total: number }> {
    return this.client.request('GET', `/api/v1/connectors/${connectorId}/syncs`, {
      params: { limit },
    });
  }

  /**
   * Cancel a running sync operation.
   *
   * @param connectorId - Connector ID
   * @param syncId - Sync operation ID
   */
  async cancelSync(
    connectorId: string,
    syncId: string
  ): Promise<{ cancelled: boolean; message: string }> {
    return this.client.request('POST', `/api/v1/connectors/${connectorId}/syncs/${syncId}/cancel`);
  }

  // ===========================================================================
  // Health and Monitoring
  // ===========================================================================

  /**
   * Test connectivity for a connector.
   *
   * @param connectorId - Connector ID
   */
  async testConnection(connectorId: string): Promise<ConnectionTestResult> {
    return this.client.request('POST', `/api/v1/connectors/${connectorId}/test`);
  }

  /**
   * Get health status of a connector.
   *
   * @param connectorId - Connector ID
   */
  async getHealth(connectorId: string): Promise<ConnectorHealth> {
    return this.client.request('GET', `/api/v1/connectors/${connectorId}/health`);
  }
}
