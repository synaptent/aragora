/**
 * Aragora SDK Client Tests
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AragoraClient, createClient } from '../client';
import type {
  GauntletRunRequest,
  KnowledgeEntry,
} from '../types';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('AragoraClient', () => {
  let client: AragoraClient;

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
    client = createClient({
      baseUrl: 'https://api.example.com',
      apiKey: 'test-api-key',
      retryEnabled: false,  // Disable retries for predictable test behavior
    });
  });

  describe('constructor', () => {
    it('should create a client with config', () => {
      const client = createClient({
        baseUrl: 'https://api.example.com',
        apiKey: 'test-key',
      });
      expect(client).toBeInstanceOf(AragoraClient);
    });

    it('should handle trailing slashes in baseUrl', () => {
      const client = createClient({
        baseUrl: 'https://api.example.com/',
      });
      expect(client).toBeInstanceOf(AragoraClient);
    });
  });

  describe('health', () => {
    it('should get health status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ status: 'healthy' })),
      });

      const health = await client.getHealth();
      expect(health.status).toBe('healthy');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/api/health',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-api-key',
          }),
        })
      );
    });
  });

  describe('gauntlet', () => {
    it('should run a gauntlet', async () => {
      const mockResponse = {
        gauntlet_id: 'gauntlet-123',
        status: 'pending',
        status_url: '/api/v1/gauntlet/gauntlet-123',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const request: GauntletRunRequest = {
        input: 'Test input',
        profile: 'comprehensive',
      };

      const response = await client.runGauntlet(request);

      expect(response.gauntlet_id).toBe('gauntlet-123');
      expect(response.status).toBe('pending');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/api/v1/gauntlet/run',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(request),
        })
      );
    });

    it('should get gauntlet receipt', async () => {
      const mockReceipt = {
        id: 'receipt-123',
        verdict: 'APPROVED',
        confidence: 0.95,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockReceipt)),
      });

      const receipt = await client.getGauntletReceipt('receipt-123');
      expect(receipt).toEqual(mockReceipt);
    });

    it('should verify gauntlet receipt', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ valid: true, hash: 'abc123' })),
      });

      const result = await client.verifyGauntletReceipt('receipt-123');
      expect(result.valid).toBe(true);
    });
  });

  describe('knowledge', () => {
    it('should search knowledge', async () => {
      const mockResults = {
        results: [
          { id: 'k1', content: 'Test knowledge', score: 0.9 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResults)),
      });

      const results = await client.searchKnowledge('test query', { limit: 10 });
      expect(results.results).toHaveLength(1);
      expect(results.results[0].content).toBe('Test knowledge');
    });

    it('should add knowledge entry', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 'new-id', created_at: '2024-01-01' })),
      });

      const entry: KnowledgeEntry = {
        content: 'New knowledge',
        tags: ['test'],
      };

      const result = await client.addKnowledge(entry);
      expect(result.id).toBe('new-id');
    });

    it('should get knowledge stats', async () => {
      const mockStats = {
        total_entries: 100,
        by_visibility: { private: 50, team: 30, global: 20 },
        by_source: { user: 80, auto: 20 },
        storage_bytes: 1024000,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockStats)),
      });

      const stats = await client.getKnowledgeStats();
      expect(stats.total_entries).toBe(100);
    });
  });

  describe('memory', () => {
    it('should store memory', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ stored: true, tier: 'fast' })),
      });

      const result = await client.storeMemory('test-key', { data: 'test' }, {
        tier: 'fast',
        importance: 0.8,
      });

      expect(result.stored).toBe(true);
      expect(result.tier).toBe('fast');
    });

    it('should retrieve memory', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          value: { data: 'test' },
          tier: 'fast',
        })),
      });

      const result = await client.retrieveMemory('test-key');
      expect(result?.value).toEqual({ data: 'test' });
    });

    it('should return null for missing memory', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ error: 'Not found' }),
      });

      const result = await client.retrieveMemory('missing-key');
      expect(result).toBeNull();
    });

    it('should store a continuum memory entry', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 'mem-123', tier: 'slow' })),
      });

      const result = await client.storeMemoryEntry('Important insight', {
        tier: 'slow',
        importance: 0.9,
      });

      expect(result.id).toBe('mem-123');
      expect(result.tier).toBe('slow');
      const [url, init] = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
      expect(url).toContain('/api/v1/memory/store');
      expect(JSON.parse(init.body)).toEqual({
        content: 'Important insight',
        tier: 'slow',
        importance: 0.9,
      });
    });

    it('should delete a continuum memory entry by ID', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          success: true,
          message: 'Memory mem-123 deleted successfully',
        })),
      });

      const result = await client.deleteMemoryEntry('mem-123');

      expect(result.success).toBe(true);
      const [url, init] = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
      expect(url).toContain('/api/v1/memory/continuum/mem-123');
      expect(init.method).toBe('DELETE');
    });

    it('should search memory', async () => {
      const mockEntries = {
        entries: [
          { id: 'm1', content: 'Memory content', importance: 0.9 },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockEntries)),
      });

      const result = await client.searchMemory({ query: 'test' });
      expect(result.entries).toHaveLength(1);
    });
  });

  describe('explainability', () => {
    it('should get explanation', async () => {
      const mockExplanation = {
        debate_id: 'debate-123',
        summary: 'Test explanation',
        factors: [],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockExplanation)),
      });

      const result = await client.getExplanation('debate-123');
      expect(result.summary).toBe('Test explanation');
    });

    it('should get provenance', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ steps: [], sources: [] })),
      });

      const result = await client.getProvenance('debate-123');
      expect(result).toBeDefined();
    });

    it('should create batch explanation', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          batch_id: 'batch-123',
          status_url: '/api/v1/explainability/batch/batch-123',
        })),
      });

      const result = await client.createBatchExplanation({
        debate_ids: ['d1', 'd2', 'd3'],
      });

      expect(result.batch_id).toBe('batch-123');
    });
  });

  describe('workflows', () => {
    it('should list workflow templates', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ templates: [] })),
      });

      const result = await client.listWorkflowTemplates();
      expect(result.templates).toEqual([]);
    });

    it('should run workflow template', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ execution_id: 'exec-123' })),
      });

      const result = await client.runWorkflowTemplate('template-123', {
        inputs: { key: 'value' },
      });

      expect(result).toBeDefined();
    });
  });

  describe('error handling', () => {
    it('should handle 401 errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ error: 'Invalid token', code: 'INVALID_TOKEN' }),
      });

      await expect(client.getHealth()).rejects.toThrow('Invalid token');
    });

    it('should handle 429 rate limit errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 429,
        json: () => Promise.resolve({
          error: 'Rate limit exceeded',
          code: 'RATE_LIMITED',
          retry_after: 60,
        }),
      });

      await expect(client.getHealth()).rejects.toThrow('Rate limit exceeded');
    });

    it('should retry on server errors', async () => {
      // Create a client with retries enabled for this specific test
      const retryClient = createClient({
        baseUrl: 'https://api.example.com',
        apiKey: 'test-api-key',
        retryEnabled: true,
        maxRetries: 2,
      });

      // First call fails with 500
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ error: 'Internal error' }),
      });
      // Second call succeeds
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ status: 'healthy' })),
      });

      const result = await retryClient.getHealth();
      expect(result.status).toBe('healthy');
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
