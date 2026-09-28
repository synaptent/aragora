/**
 * Facts Namespace Tests
 *
 * Comprehensive tests for the FactsAPI namespace class.
 * Tests all methods including:
 * - CRUD operations for facts
 * - Relationship management
 * - Batch operations
 * - Search functionality
 * - Utility methods
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  FactsAPI,
  type Fact,
  type Relationship,
  type PaginatedFacts,
  type SearchedFact,
  type BatchCreateResponse,
  type BatchDeleteResponse,
  type FactStats,
} from '../facts';

// Helper to create a mock client
interface MockClient {
  request: ReturnType<typeof vi.fn>;
}

function createMockClient(): MockClient {
  return {
    request: vi.fn(),
  };
}

describe('FactsAPI', () => {
  let mockClient: MockClient;
  let factsApi: FactsAPI;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = createMockClient();
    factsApi = new FactsAPI(mockClient);
  });

  // ===========================================================================
  // Fact CRUD Operations
  // ===========================================================================

  describe('Fact CRUD Operations', () => {
    describe('createFact', () => {
      it('should create a fact with required fields', async () => {
        const mockFact: Fact = {
          id: 'fact-123',
          content: 'TypeScript is a superset of JavaScript',
          source: 'official-docs',
          confidence: 0.95,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockFact);

        const result = await factsApi.createFact({
          content: 'TypeScript is a superset of JavaScript',
          source: 'official-docs',
          confidence: 0.95,
        });

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts',
          { json: { content: 'TypeScript is a superset of JavaScript', source: 'official-docs', confidence: 0.95 } }
        );
        expect(result.id).toBe('fact-123');
        expect(result.content).toBe('TypeScript is a superset of JavaScript');
      });

      it('should create a fact with metadata', async () => {
        const mockFact: Fact = {
          id: 'fact-456',
          content: 'React uses virtual DOM',
          source: 'react-docs',
          confidence: 0.9,
          metadata: { category: 'frontend', version: '18' },
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockFact);

        const result = await factsApi.createFact({
          content: 'React uses virtual DOM',
          source: 'react-docs',
          confidence: 0.9,
          metadata: { category: 'frontend', version: '18' },
        });

        expect(result.metadata).toEqual({ category: 'frontend', version: '18' });
      });

      it('should create a fact with tags', async () => {
        const mockFact: Fact = {
          id: 'fact-789',
          content: 'Node.js is asynchronous',
          source: 'node-docs',
          confidence: 0.99,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockFact);

        await factsApi.createFact({
          content: 'Node.js is asynchronous',
          source: 'node-docs',
          tags: ['nodejs', 'async', 'javascript'],
        });

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts',
          expect.objectContaining({
            json: expect.objectContaining({
              tags: ['nodejs', 'async', 'javascript'],
            }),
          })
        );
      });
    });

    describe('getFact', () => {
      it('should get a fact by ID', async () => {
        const mockFact: Fact = {
          id: 'fact-123',
          content: 'Python is interpreted',
          source: 'python-docs',
          confidence: 0.99,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockFact);

        const result = await factsApi.getFact('fact-123');

        expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/facts/fact-123');
        expect(result.id).toBe('fact-123');
        expect(result.content).toBe('Python is interpreted');
      });
    });

    describe('updateFact', () => {
      it('should update a fact with partial data', async () => {
        const mockFact: Fact = {
          id: 'fact-123',
          content: 'Updated content',
          source: 'new-source',
          confidence: 0.85,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockFact);

        const result = await factsApi.updateFact('fact-123', {
          content: 'Updated content',
          confidence: 0.85,
        });

        expect(mockClient.request).toHaveBeenCalledWith(
          'PATCH',
          '/api/v1/facts/fact-123',
          { json: { content: 'Updated content', confidence: 0.85 } }
        );
        expect(result.content).toBe('Updated content');
      });

      it('should update a fact with new metadata', async () => {
        const mockFact: Fact = {
          id: 'fact-123',
          content: 'Original content',
          source: 'source',
          confidence: 0.9,
          metadata: { verified: true, reviewer: 'admin' },
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockFact);

        const result = await factsApi.updateFact('fact-123', {
          metadata: { verified: true, reviewer: 'admin' },
        });

        expect(result.metadata).toEqual({ verified: true, reviewer: 'admin' });
      });
    });

    describe('deleteFact', () => {
      it('should delete a fact', async () => {
        mockClient.request.mockResolvedValueOnce(undefined);

        await expect(factsApi.deleteFact('fact-123')).resolves.toBeUndefined();

        expect(mockClient.request).toHaveBeenCalledWith('DELETE', '/api/v1/facts/fact-123');
      });
    });

    describe('listFacts', () => {
      it('should list facts with pagination', async () => {
        const mockResponse: PaginatedFacts = {
          facts: [
            { id: 'f1', content: 'Fact 1', source: 's1', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
            { id: 'f2', content: 'Fact 2', source: 's2', confidence: 0.8, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
          ],
          total: 100,
          offset: 0,
          limit: 10,
          has_more: true,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.listFacts({ limit: 10, offset: 0 });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts',
          { params: { limit: 10, offset: 0 } }
        );
        expect(result.facts).toHaveLength(2);
        expect(result.total).toBe(100);
        expect(result.has_more).toBe(true);
      });

      it('should filter facts by source', async () => {
        const mockResponse: PaginatedFacts = {
          facts: [
            { id: 'f1', content: 'Fact 1', source: 'official', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
          ],
          total: 1,
          offset: 0,
          limit: 10,
          has_more: false,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.listFacts({ source: 'official' });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts',
          { params: { source: 'official' } }
        );
        expect(result.facts[0].source).toBe('official');
      });

      it('should filter facts by confidence range', async () => {
        const mockResponse: PaginatedFacts = {
          facts: [
            { id: 'f1', content: 'High confidence', source: 's1', confidence: 0.95, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
          ],
          total: 1,
          offset: 0,
          limit: 10,
          has_more: false,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.listFacts({ min_confidence: 0.9, max_confidence: 1.0 });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts',
          { params: { min_confidence: 0.9, max_confidence: 1.0 } }
        );
        expect(result.facts[0].confidence).toBeGreaterThanOrEqual(0.9);
      });

      it('should sort facts by created_at', async () => {
        const mockResponse: PaginatedFacts = {
          facts: [],
          total: 0,
          offset: 0,
          limit: 10,
          has_more: false,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        await factsApi.listFacts({ sort_by: 'created_at', sort_order: 'desc' });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts',
          { params: { sort_by: 'created_at', sort_order: 'desc' } }
        );
      });
    });
  });

  // ===========================================================================
  // Search Operations
  // ===========================================================================

  describe('Search Operations', () => {
    describe('searchFacts', () => {
      it('should search facts with semantic search', async () => {
        const mockResults: SearchedFact[] = [
          {
            id: 'f1',
            content: 'Machine learning uses algorithms',
            source: 'ml-docs',
            confidence: 0.9,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            relevance: 0.95,
            highlights: ['Machine learning uses algorithms'],
          },
        ];
        mockClient.request.mockResolvedValueOnce({ results: mockResults });

        const result = await factsApi.searchFacts('machine learning', { semantic: true });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/search',
          { params: { query: 'machine learning', semantic: true } }
        );
        expect(result).toHaveLength(1);
        expect(result[0].relevance).toBe(0.95);
      });

      it('should search with minimum relevance filter', async () => {
        const mockResults: SearchedFact[] = [
          {
            id: 'f1',
            content: 'Highly relevant',
            source: 's1',
            confidence: 0.9,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            relevance: 0.85,
          },
        ];
        mockClient.request.mockResolvedValueOnce({ results: mockResults });

        const result = await factsApi.searchFacts('query', { min_relevance: 0.8 });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/search',
          { params: { query: 'query', min_relevance: 0.8 } }
        );
        expect(result[0].relevance).toBeGreaterThanOrEqual(0.8);
      });

      it('should search with source filter', async () => {
        mockClient.request.mockResolvedValueOnce({ results: [] });

        await factsApi.searchFacts('query', { source: 'official-docs' });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/search',
          { params: { query: 'query', source: 'official-docs' } }
        );
      });

      it('should search with tags filter', async () => {
        mockClient.request.mockResolvedValueOnce({ results: [] });

        await factsApi.searchFacts('query', { tags: ['javascript', 'typescript'] });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/search',
          { params: { query: 'query', tags: ['javascript', 'typescript'] } }
        );
      });

      it('should search with limit', async () => {
        mockClient.request.mockResolvedValueOnce({ results: [] });

        await factsApi.searchFacts('query', { limit: 5 });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/search',
          { params: { query: 'query', limit: 5 } }
        );
      });
    });
  });

  // ===========================================================================
  // Relationship Operations
  // ===========================================================================

  describe('Relationship Operations', () => {
    describe('createRelationship', () => {
      it('should create a relationship between facts', async () => {
        const mockRel: Relationship = {
          id: 'rel-123',
          source_fact_id: 'fact-1',
          target_fact_id: 'fact-2',
          relationship_type: 'supports',
          weight: 0.9,
          created_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockRel);

        const result = await factsApi.createRelationship({
          source_fact_id: 'fact-1',
          target_fact_id: 'fact-2',
          relationship_type: 'supports',
          weight: 0.9,
        });

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts/relationships',
          {
            json: {
              source_fact_id: 'fact-1',
              target_fact_id: 'fact-2',
              relationship_type: 'supports',
              weight: 0.9,
            },
          }
        );
        expect(result.id).toBe('rel-123');
        expect(result.relationship_type).toBe('supports');
      });

      it('should create a contradicts relationship', async () => {
        const mockRel: Relationship = {
          id: 'rel-456',
          source_fact_id: 'fact-1',
          target_fact_id: 'fact-2',
          relationship_type: 'contradicts',
          weight: 0.8,
          created_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockRel);

        const result = await factsApi.createRelationship({
          source_fact_id: 'fact-1',
          target_fact_id: 'fact-2',
          relationship_type: 'contradicts',
          weight: 0.8,
        });

        expect(result.relationship_type).toBe('contradicts');
      });
    });

    describe('getRelationships', () => {
      it('should get relationships for a fact', async () => {
        const mockRels: Relationship[] = [
          { id: 'r1', source_fact_id: 'f1', target_fact_id: 'f2', relationship_type: 'supports', weight: 0.9, created_at: '2024-01-01T00:00:00Z' },
          { id: 'r2', source_fact_id: 'f1', target_fact_id: 'f3', relationship_type: 'contradicts', weight: 0.7, created_at: '2024-01-01T00:00:00Z' },
        ];
        mockClient.request.mockResolvedValueOnce({ relationships: mockRels });

        const result = await factsApi.getRelationships('f1');

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/f1/relationships',
          { params: undefined }
        );
        expect(result).toHaveLength(2);
      });

      it('should filter relationships by type', async () => {
        const mockRels: Relationship[] = [
          { id: 'r1', source_fact_id: 'f1', target_fact_id: 'f2', relationship_type: 'supports', weight: 0.9, created_at: '2024-01-01T00:00:00Z' },
        ];
        mockClient.request.mockResolvedValueOnce({ relationships: mockRels });

        const result = await factsApi.getRelationships('f1', { relationship_type: 'supports' });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/f1/relationships',
          { params: { relationship_type: 'supports' } }
        );
        expect(result[0].relationship_type).toBe('supports');
      });

      it('should filter by direction', async () => {
        mockClient.request.mockResolvedValueOnce({ relationships: [] });

        await factsApi.getRelationships('f1', { direction: 'outgoing' });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/f1/relationships',
          { params: { direction: 'outgoing' } }
        );
      });

      it('should filter by minimum weight', async () => {
        mockClient.request.mockResolvedValueOnce({ relationships: [] });

        await factsApi.getRelationships('f1', { min_weight: 0.5 });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/f1/relationships',
          { params: { min_weight: 0.5 } }
        );
      });
    });

    describe('getRelationship', () => {
      it('should get a specific relationship by ID', async () => {
        const mockRel: Relationship = {
          id: 'rel-123',
          source_fact_id: 'f1',
          target_fact_id: 'f2',
          relationship_type: 'elaborates',
          weight: 0.85,
          created_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockRel);

        const result = await factsApi.getRelationship('rel-123');

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/relationships/rel-123'
        );
        expect(result.id).toBe('rel-123');
      });
    });

    describe('updateRelationship', () => {
      it('should update a relationship', async () => {
        const mockRel: Relationship = {
          id: 'rel-123',
          source_fact_id: 'fact-1',
          target_fact_id: 'fact-2',
          relationship_type: 'elaborates',
          weight: 0.8,
          created_at: '2024-01-01T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockRel);

        const result = await factsApi.updateRelationship('rel-123', {
          relationship_type: 'elaborates',
          weight: 0.8,
        });

        expect(mockClient.request).toHaveBeenCalledWith(
          'PATCH',
          '/api/v1/facts/relationships/rel-123',
          { json: { relationship_type: 'elaborates', weight: 0.8 } }
        );
        expect(result.weight).toBe(0.8);
      });
    });

    describe('deleteRelationship', () => {
      it('should delete a relationship', async () => {
        mockClient.request.mockResolvedValueOnce(undefined);

        await expect(factsApi.deleteRelationship('rel-123')).resolves.toBeUndefined();

        expect(mockClient.request).toHaveBeenCalledWith(
          'DELETE',
          '/api/v1/facts/relationships/rel-123'
        );
      });
    });
  });

  // ===========================================================================
  // Batch Operations
  // ===========================================================================

  describe('Batch Operations', () => {
    describe('batchCreateFacts', () => {
      it('should batch create facts', async () => {
        const mockResponse: BatchCreateResponse = {
          created: [
            { id: 'f1', content: 'Fact 1', source: 's1', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
            { id: 'f2', content: 'Fact 2', source: 's2', confidence: 0.8, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
          ],
          failed: [],
          total_created: 2,
          total_failed: 0,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.batchCreateFacts([
          { content: 'Fact 1', source: 's1', confidence: 0.9 },
          { content: 'Fact 2', source: 's2', confidence: 0.8 },
        ]);

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts/batch',
          {
            json: {
              facts: [
                { content: 'Fact 1', source: 's1', confidence: 0.9 },
                { content: 'Fact 2', source: 's2', confidence: 0.8 },
              ],
            },
          }
        );
        expect(result.total_created).toBe(2);
        expect(result.total_failed).toBe(0);
      });

      it('should handle partial failures in batch create', async () => {
        const mockResponse: BatchCreateResponse = {
          created: [
            { id: 'f1', content: 'Fact 1', source: 's1', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
          ],
          failed: [
            { index: 1, error: 'Invalid content', request: { content: '', source: 's2' } },
          ],
          total_created: 1,
          total_failed: 1,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.batchCreateFacts([
          { content: 'Fact 1', source: 's1', confidence: 0.9 },
          { content: '', source: 's2' },
        ]);

        expect(result.total_created).toBe(1);
        expect(result.total_failed).toBe(1);
        expect(result.failed[0].error).toBe('Invalid content');
      });
    });

    describe('batchDeleteFacts', () => {
      it('should batch delete facts', async () => {
        const mockResponse: BatchDeleteResponse = {
          deleted: ['f1', 'f2', 'f3'],
          failed: [],
          total_deleted: 3,
          total_failed: 0,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.batchDeleteFacts(['f1', 'f2', 'f3']);

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts/batch/delete',
          { json: { ids: ['f1', 'f2', 'f3'] } }
        );
        expect(result.total_deleted).toBe(3);
        expect(result.deleted).toEqual(['f1', 'f2', 'f3']);
      });

      it('should handle partial failures in batch delete', async () => {
        const mockResponse: BatchDeleteResponse = {
          deleted: ['f1', 'f2'],
          failed: [{ id: 'f3', error: 'Not found' }],
          total_deleted: 2,
          total_failed: 1,
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.batchDeleteFacts(['f1', 'f2', 'f3']);

        expect(result.total_deleted).toBe(2);
        expect(result.total_failed).toBe(1);
        expect(result.failed[0].error).toBe('Not found');
      });
    });
  });

  // ===========================================================================
  // Utility Methods
  // ===========================================================================

  describe('Utility Methods', () => {
    describe('getStats', () => {
      it('should get fact statistics', async () => {
        const mockStats: FactStats = {
          total_facts: 1000,
          total_relationships: 500,
          by_source: { docs: 400, manual: 600 },
          average_confidence: 0.85,
          created_last_24h: 50,
          updated_last_24h: 100,
        };
        mockClient.request.mockResolvedValueOnce(mockStats);

        const result = await factsApi.getStats();

        expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/facts/stats');
        expect(result.total_facts).toBe(1000);
        expect(result.average_confidence).toBe(0.85);
      });
    });

    describe('exists', () => {
      it('should return true when fact exists', async () => {
        mockClient.request.mockResolvedValueOnce({ exists: true });

        const result = await factsApi.exists('fact-123');

        expect(mockClient.request).toHaveBeenCalledWith('HEAD', '/api/v1/facts/fact-123');
        expect(result).toBe(true);
      });

      it('should return false when fact does not exist', async () => {
        mockClient.request.mockRejectedValueOnce(new Error('Not found'));

        const result = await factsApi.exists('nonexistent');

        expect(result).toBe(false);
      });

      it('should return true when response has no exists field', async () => {
        mockClient.request.mockResolvedValueOnce({});

        const result = await factsApi.exists('fact-123');

        expect(result).toBe(true);
      });
    });

    describe('getRelatedFacts', () => {
      it('should get related facts', async () => {
        const mockResponse = {
          related: [
            {
              fact: { id: 'f2', content: 'Related fact', source: 's1', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
              relationship: { id: 'r1', source_fact_id: 'f1', target_fact_id: 'f2', relationship_type: 'supports', weight: 0.8, created_at: '2024-01-01T00:00:00Z' },
            },
          ],
        };
        mockClient.request.mockResolvedValueOnce(mockResponse);

        const result = await factsApi.getRelatedFacts('f1');

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/f1/related',
          { params: undefined }
        );
        expect(result).toHaveLength(1);
        expect(result[0].fact.id).toBe('f2');
        expect(result[0].relationship.relationship_type).toBe('supports');
      });

      it('should get related facts with filters', async () => {
        mockClient.request.mockResolvedValueOnce({ related: [] });

        await factsApi.getRelatedFacts('f1', { relationship_type: 'supports', limit: 10 });

        expect(mockClient.request).toHaveBeenCalledWith(
          'GET',
          '/api/v1/facts/f1/related',
          { params: { relationship_type: 'supports', limit: 10 } }
        );
      });
    });

    describe('validateContent', () => {
      it('should validate fact content - valid', async () => {
        const mockValidation = {
          valid: true,
          issues: [],
          suggestions: ['Consider adding source citation'],
        };
        mockClient.request.mockResolvedValueOnce(mockValidation);

        const result = await factsApi.validateContent('Valid fact content');

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts/validate',
          { json: { content: 'Valid fact content' } }
        );
        expect(result.valid).toBe(true);
        expect(result.issues).toHaveLength(0);
      });

      it('should validate fact content - invalid', async () => {
        const mockValidation = {
          valid: false,
          issues: ['Content too short', 'Missing context'],
        };
        mockClient.request.mockResolvedValueOnce(mockValidation);

        const result = await factsApi.validateContent('X');

        expect(result.valid).toBe(false);
        expect(result.issues).toContain('Content too short');
      });
    });

    describe('mergeFacts', () => {
      it('should merge two facts', async () => {
        const mockMerged: Fact = {
          id: 'fact-target',
          content: 'Merged content',
          source: 'merged-source',
          confidence: 0.95,
          metadata: { merged_from: 'fact-source' },
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockMerged);

        const result = await factsApi.mergeFacts('fact-source', 'fact-target', {
          transfer_relationships: true,
          merge_metadata: true,
        });

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts/merge',
          {
            json: {
              source_id: 'fact-source',
              target_id: 'fact-target',
              transfer_relationships: true,
              merge_metadata: true,
            },
          }
        );
        expect(result.id).toBe('fact-target');
      });

      it('should merge facts without options', async () => {
        const mockMerged: Fact = {
          id: 'fact-target',
          content: 'Content',
          source: 'source',
          confidence: 0.9,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        };
        mockClient.request.mockResolvedValueOnce(mockMerged);

        await factsApi.mergeFacts('fact-source', 'fact-target');

        expect(mockClient.request).toHaveBeenCalledWith(
          'POST',
          '/api/v1/facts/merge',
          {
            json: {
              source_id: 'fact-source',
              target_id: 'fact-target',
            },
          }
        );
      });
    });
  });
});
