/**
 * Connectors Namespace API
 *
 * Provides read access to configured enterprise data source connectors
 * (GitHub Enterprise, S3, PostgreSQL, MongoDB, FHIR).
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
 * // Get one connector
 * const connector = await client.connectors.get(connectors[0].id);
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
}
