/**
 * Connectors Namespace Tests
 *
 * Comprehensive tests for the connectors namespace API including:
 * - Connector CRUD operations
 * - Sync operations
 * - Health and monitoring
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { ConnectorsAPI } from '../connectors';

interface MockClient {
  request: Mock;
}

describe('ConnectorsAPI Namespace', () => {
  let api: ConnectorsAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
    };
    api = new ConnectorsAPI(mockClient as any);
  });

  // ===========================================================================
  // Connector Management
  // ===========================================================================

  describe('Connector Management', () => {
    it('should list connectors', async () => {
      const mockConnectors = {
        connectors: [
          {
            id: 'c1',
            name: 'Production DB',
            type: 'postgresql',
            enabled: true,
            health_status: 'healthy',
          },
          { id: 'c2', name: 'S3 Bucket', type: 's3', enabled: true, health_status: 'healthy' },
        ],
        pagination: { limit: 50, offset: 0, total: 2, has_more: false },
      };
      mockClient.request.mockResolvedValue(mockConnectors);

      const result = await api.list();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors', {
        params: { limit: 50, offset: 0 },
      });
      expect(result.connectors).toHaveLength(2);
    });

    it('should list connectors by type', async () => {
      const mockConnectors = {
        connectors: [{ id: 'c1', type: 'postgresql' }],
        pagination: { limit: 50, offset: 0, total: 1, has_more: false },
      };
      mockClient.request.mockResolvedValue(mockConnectors);

      const result = await api.list({ connectorType: 'postgresql' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors', {
        params: { limit: 50, offset: 0, type: 'postgresql' },
      });
      expect(result.connectors).toHaveLength(1);
    });

    it('should list connectors with pagination', async () => {
      const mockConnectors = {
        connectors: [{ id: 'c3' }],
        pagination: { limit: 10, offset: 20, total: 25, has_more: false },
      };
      mockClient.request.mockResolvedValue(mockConnectors);

      const result = await api.list({ limit: 10, offset: 20 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors', {
        params: { limit: 10, offset: 20 },
      });
      expect(result.pagination.offset).toBe(20);
    });

    it('should get connector by ID', async () => {
      const mockConnector = {
        id: 'c1',
        name: 'Production DB',
        type: 'postgresql',
        config: { host: 'db.example.com', database: 'production' },
        schedule: 'daily',
        enabled: true,
        health_status: 'healthy',
      };
      mockClient.request.mockResolvedValue(mockConnector);

      const result = await api.get('c1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors/c1');
      expect(result.name).toBe('Production DB');
    });

    it('should create connector', async () => {
      const mockConnector = {
        id: 'c_new',
        name: 'New Connector',
        type: 'mongodb',
        config: { uri: 'mongodb://...' },
        schedule: 'hourly',
        enabled: true,
        health_status: 'unknown',
      };
      mockClient.request.mockResolvedValue(mockConnector);

      const result = await api.create('New Connector', 'mongodb', { uri: 'mongodb://...' }, 'hourly');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/connectors', {
        json: {
          name: 'New Connector',
          type: 'mongodb',
          config: { uri: 'mongodb://...' },
          schedule: 'hourly',
        },
      });
      expect(result.id).toBe('c_new');
    });

    it('should create connector with default schedule', async () => {
      const mockConnector = {
        id: 'c_new',
        name: 'S3 Bucket',
        type: 's3',
        schedule: 'daily',
      };
      mockClient.request.mockResolvedValue(mockConnector);

      const result = await api.create('S3 Bucket', 's3', { bucket: 'my-bucket' });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/connectors', {
        json: {
          name: 'S3 Bucket',
          type: 's3',
          config: { bucket: 'my-bucket' },
          schedule: 'daily',
        },
      });
      expect(result.schedule).toBe('daily');
    });

    it('should update connector', async () => {
      const mockConnector = {
        id: 'c1',
        name: 'Updated Name',
        schedule: 'hourly',
        enabled: false,
      };
      mockClient.request.mockResolvedValue(mockConnector);

      const result = await api.update('c1', {
        name: 'Updated Name',
        schedule: 'hourly',
        enabled: false,
      });

      expect(mockClient.request).toHaveBeenCalledWith('PATCH', '/api/v1/connectors/c1', {
        json: {
          name: 'Updated Name',
          schedule: 'hourly',
          enabled: false,
        },
      });
      expect(result.name).toBe('Updated Name');
    });

    it('should delete connector', async () => {
      mockClient.request.mockResolvedValue({ deleted: true, message: 'Connector deleted' });

      const result = await api.delete('c1');

      expect(mockClient.request).toHaveBeenCalledWith('DELETE', '/api/v1/connectors/c1');
      expect(result.deleted).toBe(true);
    });
  });

  // ===========================================================================
  // Sync Operations
  // ===========================================================================

  describe('Sync Operations', () => {
    it('should trigger incremental sync', async () => {
      const mockSync = {
        sync_id: 'sync_123',
        status: 'pending',
        message: 'Sync initiated',
      };
      mockClient.request.mockResolvedValue(mockSync);

      const result = await api.triggerSync('c1');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/connectors/c1/sync', {
        json: { full_sync: false },
      });
      expect(result.sync_id).toBe('sync_123');
    });

    it('should trigger full sync', async () => {
      const mockSync = {
        sync_id: 'sync_124',
        status: 'pending',
        message: 'Full sync initiated',
      };
      mockClient.request.mockResolvedValue(mockSync);

      const result = await api.triggerSync('c1', true);

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/connectors/c1/sync', {
        json: { full_sync: true },
      });
    });

    it('should get sync status', async () => {
      const mockSync = {
        sync_id: 'sync_123',
        connector_id: 'c1',
        status: 'running',
        full_sync: false,
        started_at: '2024-01-20T10:00:00Z',
        records_processed: 5000,
        progress_percent: 50,
      };
      mockClient.request.mockResolvedValue(mockSync);

      const result = await api.getSyncStatus('c1', 'sync_123');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors/c1/syncs/sync_123');
      expect(result.status).toBe('running');
      expect(result.progress_percent).toBe(50);
    });

    it('should list sync operations', async () => {
      const mockSyncs = {
        syncs: [
          { sync_id: 'sync_1', status: 'completed', records_processed: 10000 },
          { sync_id: 'sync_2', status: 'failed', error_message: 'Connection timeout' },
        ],
        total: 2,
      };
      mockClient.request.mockResolvedValue(mockSyncs);

      const result = await api.listSyncs('c1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors/c1/syncs', {
        params: { limit: 20 },
      });
      expect(result.syncs).toHaveLength(2);
    });

    it('should list syncs with custom limit', async () => {
      const mockSyncs = { syncs: [], total: 0 };
      mockClient.request.mockResolvedValue(mockSyncs);

      await api.listSyncs('c1', 50);

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors/c1/syncs', {
        params: { limit: 50 },
      });
    });

    it('should cancel sync', async () => {
      mockClient.request.mockResolvedValue({ cancelled: true, message: 'Sync cancelled' });

      const result = await api.cancelSync('c1', 'sync_123');

      expect(mockClient.request).toHaveBeenCalledWith(
        'POST',
        '/api/v1/connectors/c1/syncs/sync_123/cancel'
      );
      expect(result.cancelled).toBe(true);
    });
  });

  // ===========================================================================
  // Health and Monitoring
  // ===========================================================================

  describe('Health and Monitoring', () => {
    it('should test connection', async () => {
      const mockTest = {
        connection_ok: true,
        latency_ms: 25,
        tested_at: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockTest);

      const result = await api.testConnection('c1');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/connectors/c1/test');
      expect(result.connection_ok).toBe(true);
      expect(result.latency_ms).toBe(25);
    });

    it('should test connection failure', async () => {
      const mockTest = {
        connection_ok: false,
        latency_ms: 5000,
        error_message: 'Connection timeout',
        tested_at: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockTest);

      const result = await api.testConnection('c1');

      expect(result.connection_ok).toBe(false);
      expect(result.error_message).toBe('Connection timeout');
    });

    it('should get connector health', async () => {
      const mockHealth = {
        connector_id: 'c1',
        status: 'healthy',
        last_sync_at: '2024-01-20T09:00:00Z',
        last_sync_status: 'completed',
        error_count_24h: 0,
        avg_sync_duration_ms: 120000,
        checked_at: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockHealth);

      const result = await api.getHealth('c1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/connectors/c1/health');
      expect(result.status).toBe('healthy');
      expect(result.error_count_24h).toBe(0);
    });

    it('should show degraded health', async () => {
      const mockHealth = {
        connector_id: 'c1',
        status: 'degraded',
        last_sync_status: 'failed',
        error_count_24h: 5,
        last_error: 'Authentication failed',
        checked_at: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockHealth);

      const result = await api.getHealth('c1');

      expect(result.status).toBe('degraded');
      expect(result.error_count_24h).toBe(5);
      expect(result.last_error).toBe('Authentication failed');
    });
  });
});
