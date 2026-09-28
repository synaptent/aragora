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
  });
});
