/**
 * Aragora SDK Facts API Tests
 *
 * Tests for the Facts namespace API (client.facts).
 * Covers CRUD operations for facts and relationships, batch operations,
 * and search functionality.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createClient } from '../client';
import type {
  Fact,
  Relationship,
  CreateFactRequest,
  UpdateFactRequest,
  PaginatedFacts,
  SearchedFact,
  BatchCreateResponse,
  BatchDeleteResponse,
  FactStats,
} from '../namespaces/facts';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('Facts API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ===========================================================================
  // Namespace Exposure Tests
  // ===========================================================================

  describe('namespace exposure', () => {
    it('should expose facts namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.facts).toBeDefined();
    });

    it('should expose all CRUD methods', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(typeof client.facts.createFact).toBe('function');
      expect(typeof client.facts.getFact).toBe('function');
      expect(typeof client.facts.updateFact).toBe('function');
      expect(typeof client.facts.deleteFact).toBe('function');
      expect(typeof client.facts.listFacts).toBe('function');
      expect(typeof client.facts.searchFacts).toBe('function');
    });

    it('should expose relationship methods', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(typeof client.facts.createRelationship).toBe('function');
      expect(typeof client.facts.getRelationships).toBe('function');
      expect(typeof client.facts.updateRelationship).toBe('function');
      expect(typeof client.facts.deleteRelationship).toBe('function');
    });

    it('should expose batch methods', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(typeof client.facts.batchCreateFacts).toBe('function');
      expect(typeof client.facts.batchDeleteFacts).toBe('function');
    });

    it('should expose utility methods', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(typeof client.facts.getStats).toBe('function');
      expect(typeof client.facts.exists).toBe('function');
      expect(typeof client.facts.getRelatedFacts).toBe('function');
      expect(typeof client.facts.validateContent).toBe('function');
      expect(typeof client.facts.mergeFacts).toBe('function');
    });
  });

  // ===========================================================================
  // Fact CRUD Tests
  // ===========================================================================

  describe('createFact', () => {
    it('should create a fact with required fields', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockFact: Fact = {
        id: 'fact-123',
        content: 'TypeScript is a superset of JavaScript',
        source: 'official-docs',
        confidence: 0.95,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockFact)),
      });

      const result = await client.facts.createFact({
        content: 'TypeScript is a superset of JavaScript',
        source: 'official-docs',
        confidence: 0.95,
      });

      expect(result.id).toBe('fact-123');
      expect(result.content).toBe('TypeScript is a superset of JavaScript');
      expect(result.confidence).toBe(0.95);
    });

    it('should create a fact with metadata', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockFact: Fact = {
        id: 'fact-456',
        content: 'React uses virtual DOM',
        source: 'react-docs',
        confidence: 0.9,
        metadata: { category: 'frontend', version: '18' },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockFact)),
      });

      const result = await client.facts.createFact({
        content: 'React uses virtual DOM',
        source: 'react-docs',
        confidence: 0.9,
        metadata: { category: 'frontend', version: '18' },
      });

      expect(result.metadata).toEqual({ category: 'frontend', version: '18' });
    });
  });

  describe('getFact', () => {
    it('should get a fact by ID', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockFact: Fact = {
        id: 'fact-123',
        content: 'Python is interpreted',
        source: 'python-docs',
        confidence: 0.99,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockFact)),
      });

      const result = await client.facts.getFact('fact-123');
      expect(result.id).toBe('fact-123');
      expect(result.content).toBe('Python is interpreted');
    });
  });

  describe('updateFact', () => {
    it('should update a fact', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockFact: Fact = {
        id: 'fact-123',
        content: 'Updated content',
        source: 'new-source',
        confidence: 0.85,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockFact)),
      });

      const result = await client.facts.updateFact('fact-123', {
        content: 'Updated content',
        confidence: 0.85,
      });

      expect(result.content).toBe('Updated content');
      expect(result.confidence).toBe(0.85);
    });
  });

  describe('deleteFact', () => {
    it('should delete a fact', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(''),
      });

      await expect(client.facts.deleteFact('fact-123')).resolves.toBeUndefined();
    });
  });

  describe('listFacts', () => {
    it('should list facts with pagination', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

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

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const result = await client.facts.listFacts({ limit: 10, offset: 0 });
      expect(result.facts).toHaveLength(2);
      expect(result.total).toBe(100);
      expect(result.has_more).toBe(true);
    });

    it('should filter facts by confidence', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockResponse: PaginatedFacts = {
        facts: [
          { id: 'f1', content: 'High confidence fact', source: 's1', confidence: 0.95, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
        ],
        total: 1,
        offset: 0,
        limit: 10,
        has_more: false,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const result = await client.facts.listFacts({ min_confidence: 0.9 });
      expect(result.facts).toHaveLength(1);
      expect(result.facts[0].confidence).toBeGreaterThanOrEqual(0.9);
    });
  });

  describe('searchFacts', () => {
    it('should search facts with semantic search', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

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

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ results: mockResults })),
      });

      const result = await client.facts.searchFacts('machine learning', { semantic: true });
      expect(result).toHaveLength(1);
      expect(result[0].relevance).toBe(0.95);
    });

    it('should search with minimum relevance filter', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockResults: SearchedFact[] = [
        {
          id: 'f1',
          content: 'Highly relevant fact',
          source: 's1',
          confidence: 0.9,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
          relevance: 0.85,
        },
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ results: mockResults })),
      });

      const result = await client.facts.searchFacts('query', { min_relevance: 0.8 });
      expect(result).toHaveLength(1);
      expect(result[0].relevance).toBeGreaterThanOrEqual(0.8);
    });
  });

  // ===========================================================================
  // Relationship Tests
  // ===========================================================================

  describe('createRelationship', () => {
    it('should create a relationship between facts', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockRel: Relationship = {
        id: 'rel-123',
        source_fact_id: 'fact-1',
        target_fact_id: 'fact-2',
        relationship_type: 'supports',
        weight: 0.9,
        created_at: '2024-01-01T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRel)),
      });

      const result = await client.facts.createRelationship({
        source_fact_id: 'fact-1',
        target_fact_id: 'fact-2',
        relationship_type: 'supports',
        weight: 0.9,
      });

      expect(result.id).toBe('rel-123');
      expect(result.relationship_type).toBe('supports');
    });
  });

  describe('getRelationships', () => {
    it('should get relationships for a fact', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockRels: Relationship[] = [
        { id: 'r1', source_fact_id: 'f1', target_fact_id: 'f2', relationship_type: 'supports', weight: 0.9, created_at: '2024-01-01T00:00:00Z' },
        { id: 'r2', source_fact_id: 'f1', target_fact_id: 'f3', relationship_type: 'contradicts', weight: 0.7, created_at: '2024-01-01T00:00:00Z' },
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ relationships: mockRels })),
      });

      const result = await client.facts.getRelationships('f1');
      expect(result).toHaveLength(2);
      expect(result[0].relationship_type).toBe('supports');
    });

    it('should filter relationships by type', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockRels: Relationship[] = [
        { id: 'r1', source_fact_id: 'f1', target_fact_id: 'f2', relationship_type: 'supports', weight: 0.9, created_at: '2024-01-01T00:00:00Z' },
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ relationships: mockRels })),
      });

      const result = await client.facts.getRelationships('f1', { relationship_type: 'supports' });
      expect(result).toHaveLength(1);
      expect(result[0].relationship_type).toBe('supports');
    });
  });

  describe('updateRelationship', () => {
    it('should update a relationship', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockRel: Relationship = {
        id: 'rel-123',
        source_fact_id: 'fact-1',
        target_fact_id: 'fact-2',
        relationship_type: 'elaborates',
        weight: 0.8,
        created_at: '2024-01-01T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockRel)),
      });

      const result = await client.facts.updateRelationship('rel-123', {
        relationship_type: 'elaborates',
        weight: 0.8,
      });

      expect(result.relationship_type).toBe('elaborates');
      expect(result.weight).toBe(0.8);
    });
  });

  describe('deleteRelationship', () => {
    it('should delete a relationship', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(''),
      });

      await expect(client.facts.deleteRelationship('rel-123')).resolves.toBeUndefined();
    });
  });

  // ===========================================================================
  // Batch Operations Tests
  // ===========================================================================

  describe('batchCreateFacts', () => {
    it('should batch create facts', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockResponse: BatchCreateResponse = {
        created: [
          { id: 'f1', content: 'Fact 1', source: 's1', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
          { id: 'f2', content: 'Fact 2', source: 's2', confidence: 0.8, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
        ],
        failed: [],
        total_created: 2,
        total_failed: 0,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const result = await client.facts.batchCreateFacts([
        { content: 'Fact 1', source: 's1', confidence: 0.9 },
        { content: 'Fact 2', source: 's2', confidence: 0.8 },
      ]);

      expect(result.total_created).toBe(2);
      expect(result.total_failed).toBe(0);
      expect(result.created).toHaveLength(2);
    });

    it('should handle partial failures in batch create', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

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

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const result = await client.facts.batchCreateFacts([
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
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockResponse: BatchDeleteResponse = {
        deleted: ['f1', 'f2', 'f3'],
        failed: [],
        total_deleted: 3,
        total_failed: 0,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const result = await client.facts.batchDeleteFacts(['f1', 'f2', 'f3']);
      expect(result.total_deleted).toBe(3);
      expect(result.deleted).toEqual(['f1', 'f2', 'f3']);
    });
  });

  // ===========================================================================
  // Utility Methods Tests
  // ===========================================================================

  describe('getStats', () => {
    it('should get fact statistics', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockStats: FactStats = {
        total_facts: 1000,
        total_relationships: 500,
        by_source: { 'docs': 400, 'manual': 600 },
        average_confidence: 0.85,
        created_last_24h: 50,
        updated_last_24h: 100,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockStats)),
      });

      const result = await client.facts.getStats();
      expect(result.total_facts).toBe(1000);
      expect(result.average_confidence).toBe(0.85);
    });
  });

  describe('exists', () => {
    it('should return true when fact exists', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ exists: true })),
      });

      const result = await client.facts.exists('fact-123');
      expect(result).toBe(true);
    });

    it('should return false when fact does not exist', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockRejectedValueOnce(new Error('Not found'));

      const result = await client.facts.exists('nonexistent');
      expect(result).toBe(false);
    });
  });

  describe('getRelatedFacts', () => {
    it('should get related facts', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockResponse = {
        related: [
          {
            fact: { id: 'f2', content: 'Related fact', source: 's1', confidence: 0.9, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
            relationship: { id: 'r1', source_fact_id: 'f1', target_fact_id: 'f2', relationship_type: 'supports', weight: 0.8, created_at: '2024-01-01T00:00:00Z' },
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockResponse)),
      });

      const result = await client.facts.getRelatedFacts('f1');
      expect(result).toHaveLength(1);
      expect(result[0].fact.id).toBe('f2');
      expect(result[0].relationship.relationship_type).toBe('supports');
    });
  });

  describe('validateContent', () => {
    it('should validate fact content', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockValidation = {
        valid: true,
        issues: [],
        suggestions: ['Consider adding source citation'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockValidation)),
      });

      const result = await client.facts.validateContent('Valid fact content');
      expect(result.valid).toBe(true);
      expect(result.issues).toHaveLength(0);
    });

    it('should return issues for invalid content', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockValidation = {
        valid: false,
        issues: ['Content too short', 'Missing context'],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockValidation)),
      });

      const result = await client.facts.validateContent('X');
      expect(result.valid).toBe(false);
      expect(result.issues).toContain('Content too short');
    });
  });

  describe('mergeFacts', () => {
    it('should merge two facts', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      const mockMerged: Fact = {
        id: 'fact-target',
        content: 'Merged content',
        source: 'merged-source',
        confidence: 0.95,
        metadata: { merged_from: 'fact-source' },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify(mockMerged)),
      });

      const result = await client.facts.mergeFacts('fact-source', 'fact-target', {
        transfer_relationships: true,
        merge_metadata: true,
      });

      expect(result.id).toBe('fact-target');
    });
  });
});
