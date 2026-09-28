/**
 * Memory Namespace Tests
 *
 * Comprehensive tests for the memory namespace API including:
 * - Core CRUD operations (store, retrieve, delete, update)
 * - Memory tiers and statistics
 * - Query operations
 * - Context management
 * - Continuum operations
 * - Maintenance operations (prune, compact, sync)
 * - Tier-specific operations
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { MemoryAPI } from '../memory';
import type { MemoryEntry, MemoryStats, MemoryTierStats } from '../../types';

// Mock client interface
interface MockClient {
  storeMemory: Mock;
  retrieveMemory: Mock;
  deleteMemory: Mock;
  storeMemoryEntry: Mock;
  deleteMemoryEntry: Mock;
  getMemoryStats: Mock;
  searchMemory: Mock;
  getMemoryTiers: Mock;
  getMemoryCritiques: Mock;
  storeToContinuum: Mock;
  retrieveFromContinuum: Mock;
  getContinuumStats: Mock;
  consolidateMemory: Mock;
  request: Mock;
}

describe('MemoryAPI Namespace', () => {
  let api: MemoryAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      storeMemory: vi.fn(),
      retrieveMemory: vi.fn(),
      deleteMemory: vi.fn(),
      storeMemoryEntry: vi.fn(),
      deleteMemoryEntry: vi.fn(),
      getMemoryStats: vi.fn(),
      searchMemory: vi.fn(),
      getMemoryTiers: vi.fn(),
      getMemoryCritiques: vi.fn(),
      storeToContinuum: vi.fn(),
      retrieveFromContinuum: vi.fn(),
      getContinuumStats: vi.fn(),
      consolidateMemory: vi.fn(),
      request: vi.fn(),
    };
    api = new MemoryAPI(mockClient as any);
  });

  // ===========================================================================
  // Core CRUD Operations
  // ===========================================================================

  describe('Core CRUD Operations', () => {
    it('should store a value in memory', async () => {
      mockClient.storeMemory.mockResolvedValue({ stored: true, tier: 'fast' });

      const result = await api.store('user-preference', { theme: 'dark' });

      expect(mockClient.storeMemory).toHaveBeenCalledWith('user-preference', { theme: 'dark' }, undefined);
      expect(result.stored).toBe(true);
      expect(result.tier).toBe('fast');
    });

    it('should store a value with options', async () => {
      mockClient.storeMemory.mockResolvedValue({ stored: true, tier: 'slow' });

      const result = await api.store('important-data', { value: 123 }, {
        tier: 'slow',
        importance: 0.9,
        tags: ['critical'],
        ttl_seconds: 3600,
      });

      expect(mockClient.storeMemory).toHaveBeenCalledWith('important-data', { value: 123 }, {
        tier: 'slow',
        importance: 0.9,
        tags: ['critical'],
        ttl_seconds: 3600,
      });
      expect(result.tier).toBe('slow');
    });

    it('should retrieve a value from memory', async () => {
      mockClient.retrieveMemory.mockResolvedValue({
        value: { theme: 'dark' },
        tier: 'fast',
        metadata: { created_at: '2024-01-01T00:00:00Z' },
      });

      const result = await api.retrieve('user-preference');

      expect(mockClient.retrieveMemory).toHaveBeenCalledWith('user-preference', undefined);
      expect(result?.value).toEqual({ theme: 'dark' });
      expect(result?.tier).toBe('fast');
    });

    it('should retrieve a value from a specific tier', async () => {
      mockClient.retrieveMemory.mockResolvedValue({ value: 'data', tier: 'slow' });

      const result = await api.retrieve('key', { tier: 'slow' });

      expect(mockClient.retrieveMemory).toHaveBeenCalledWith('key', { tier: 'slow' });
      expect(result?.tier).toBe('slow');
    });

    it('should return null for non-existent key', async () => {
      mockClient.retrieveMemory.mockResolvedValue(null);

      const result = await api.retrieve('nonexistent');

      expect(result).toBeNull();
    });

    it('should delete a memory entry', async () => {
      mockClient.deleteMemory.mockResolvedValue({ deleted: true });

      const result = await api.delete('user-preference');

      expect(mockClient.deleteMemory).toHaveBeenCalledWith('user-preference', undefined);
      expect(result.deleted).toBe(true);
    });

    it('should delete a memory entry from specific tier', async () => {
      mockClient.deleteMemory.mockResolvedValue({ deleted: true });

      const result = await api.delete('key', 'glacial');

      expect(mockClient.deleteMemory).toHaveBeenCalledWith('key', 'glacial');
      expect(result.deleted).toBe(true);
    });

    it('should store a continuum entry', async () => {
      mockClient.request.mockResolvedValue({ id: 'mem-123', tier: 'fast' });

      const result = await api.storeEntry('User prefers dark theme', {
        tier: 'fast',
        importance: 0.8,
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/store', {
        body: { content: 'User prefers dark theme', tier: 'fast', importance: 0.8 },
      });
      expect(result.id).toBe('mem-123');
      expect(result.tier).toBe('fast');
    });

    it('should delete a continuum entry by ID', async () => {
      mockClient.request.mockResolvedValue({
        success: true,
        message: 'Memory mem-123 deleted successfully',
      });

      const result = await api.deleteEntry('mem-123');

      expect(mockClient.request).toHaveBeenCalledWith(
        'DELETE',
        '/api/v1/memory/continuum/mem-123'
      );
      expect(result.success).toBe(true);
    });

    it('should update an existing memory entry', async () => {
      mockClient.request.mockResolvedValue({ updated: true, tier: 'fast' });

      const result = await api.update('user-prefs', { theme: 'light' });

      expect(mockClient.request).toHaveBeenCalledWith('PUT', '/api/v1/memory/user-prefs', {
        body: { value: { theme: 'light' } },
      });
      expect(result.updated).toBe(true);
    });

    it('should update with merge option', async () => {
      mockClient.request.mockResolvedValue({ updated: true, tier: 'medium' });

      const result = await api.update('key', { newField: 'value' }, {
        tier: 'medium',
        merge: true,
        tags: ['updated'],
      });

      expect(mockClient.request).toHaveBeenCalledWith('PUT', '/api/v1/memory/key', {
        body: { value: { newField: 'value' }, tier: 'medium', merge: true, tags: ['updated'] },
      });
    });
  });

  // ===========================================================================
  // Statistics and Tiers
  // ===========================================================================

  describe('Statistics and Tiers', () => {
    it('should get memory statistics', async () => {
      mockClient.getMemoryStats.mockResolvedValue({
        total_entries: 1000,
        total_size_bytes: 1048576,
        by_tier: {
          fast: { count: 100, size: 10240 },
          medium: { count: 300, size: 102400 },
        },
      });

      const result = await api.stats();

      expect(mockClient.getMemoryStats).toHaveBeenCalled();
      expect(result.total_entries).toBe(1000);
    });

    it('should get memory tiers info', async () => {
      mockClient.getMemoryTiers.mockResolvedValue({
        tiers: [
          { name: 'fast', ttl_seconds: 60, entry_count: 100 },
          { name: 'medium', ttl_seconds: 3600, entry_count: 300 },
        ],
      });

      const result = await api.tiers();

      expect(mockClient.getMemoryTiers).toHaveBeenCalled();
      expect(result.tiers).toHaveLength(2);
    });

    it('should get tier stats', async () => {
      mockClient.request.mockResolvedValue({
        fast: { count: 100, size_bytes: 10240 },
        medium: { count: 300, size_bytes: 102400 },
        slow: { count: 500, size_bytes: 512000 },
        glacial: { count: 200, size_bytes: 1048576 },
      });

      const result = await api.getTierStats();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/tier-stats');
      expect(result.fast.count).toBe(100);
      expect(result.glacial.count).toBe(200);
    });

    it('should get archive stats', async () => {
      mockClient.request.mockResolvedValue({
        total_archived: 5000,
        archive_size_bytes: 52428800,
        oldest_entry: '2023-01-01T00:00:00Z',
        compression_ratio: 0.65,
      });

      const result = await api.getArchiveStats();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/archive-stats');
      expect(result.total_archived).toBe(5000);
    });

    it('should get memory pressure', async () => {
      mockClient.request.mockResolvedValue({
        utilization: 0.75,
        pressure_level: 'medium',
        recommendations: ['Consider pruning old entries'],
        by_tier: {
          fast: { utilization: 0.9, entries: 100 },
          medium: { utilization: 0.6, entries: 300 },
        },
      });

      const result = await api.getPressure();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/pressure');
      expect(result.pressure_level).toBe('medium');
      expect(result.recommendations).toHaveLength(1);
    });

    it('should list tiers with detailed stats', async () => {
      mockClient.request.mockResolvedValue({
        tiers: [
          { name: 'fast', ttl_seconds: 60, entry_count: 100, size_bytes: 10240 },
        ],
      });

      const result = await api.listTiers();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/tiers');
      expect(result.tiers).toHaveLength(1);
    });
  });

  // ===========================================================================
  // Search and Query
  // ===========================================================================

  describe('Search and Query', () => {
    it('should search memory entries', async () => {
      mockClient.searchMemory.mockResolvedValue({
        entries: [
          { key: 'user-1', value: { name: 'John' }, tier: 'fast' },
          { key: 'user-2', value: { name: 'Jane' }, tier: 'fast' },
        ],
      });

      const result = await api.search({ query: 'user' });

      expect(mockClient.searchMemory).toHaveBeenCalledWith({ query: 'user' });
      expect(result.entries).toHaveLength(2);
    });

    it('should query with advanced filtering', async () => {
      mockClient.request.mockResolvedValue({
        entries: [{ key: 'key1', value: 'value1' }],
        total: 50,
      });

      const result = await api.query({
        filter: { tags: ['important'] },
        sort_by: 'created_at',
        sort_order: 'desc',
        limit: 10,
        offset: 0,
        include_metadata: true,
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/query', {
        body: {
          filter: { tags: ['important'] },
          sort_by: 'created_at',
          sort_order: 'desc',
          limit: 10,
          offset: 0,
          include_metadata: true,
        },
      });
      expect(result.total).toBe(50);
    });
  });

  // ===========================================================================
  // Context Management
  // ===========================================================================

  describe('Context Management', () => {
    it('should get current context', async () => {
      mockClient.request.mockResolvedValue({
        context_id: 'ctx-123',
        data: { user_id: '123', session: 'abc' },
        created_at: '2024-01-01T00:00:00Z',
      });

      const result = await api.getContext();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/context', { params: {} });
      expect(result.context_id).toBe('ctx-123');
    });

    it('should get context by ID', async () => {
      mockClient.request.mockResolvedValue({
        context_id: 'ctx-456',
        data: { specific: 'data' },
        created_at: '2024-01-01T00:00:00Z',
      });

      const result = await api.getContext('ctx-456');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/context', {
        params: { context_id: 'ctx-456' },
      });
    });

    it('should set context', async () => {
      mockClient.request.mockResolvedValue({
        context_id: 'ctx-new',
        data: { user_id: '123' },
        created_at: '2024-01-01T00:00:00Z',
        expires_at: '2024-01-01T01:00:00Z',
      });

      const result = await api.setContext(
        { user_id: '123', session_id: 'abc' },
        { ttl_seconds: 3600 }
      );

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/context', {
        body: { data: { user_id: '123', session_id: 'abc' }, ttl_seconds: 3600 },
      });
      expect(result.context_id).toBe('ctx-new');
    });
  });

  // ===========================================================================
  // Critiques
  // ===========================================================================

  describe('Critiques', () => {
    it('should get critiques', async () => {
      mockClient.getMemoryCritiques.mockResolvedValue({
        critiques: [
          { id: 'c1', agent: 'claude', content: 'Good point' },
          { id: 'c2', agent: 'gpt-4', content: 'Consider this' },
        ],
      });

      const result = await api.critiques({ limit: 10 });

      expect(mockClient.getMemoryCritiques).toHaveBeenCalledWith({ limit: 10 });
      expect(result.critiques).toHaveLength(2);
    });

    it('should list critiques with filters', async () => {
      mockClient.request.mockResolvedValue({
        critiques: [{ id: 'c1', agent: 'claude' }],
      });

      const result = await api.listCritiques({ agent: 'claude', limit: 20 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/critiques', {
        params: { agent: 'claude', limit: 20 },
      });
    });
  });

  // ===========================================================================
  // Continuum Operations
  // ===========================================================================

  describe('Continuum Operations', () => {
    it('should store to continuum', async () => {
      mockClient.storeToContinuum.mockResolvedValue({
        id: 'entry-123',
        tier: 'medium',
        created_at: '2024-01-01T00:00:00Z',
      });

      const result = await api.storeToContinuum('Important context', {
        tier: 'medium',
        tags: ['context'],
      });

      expect(mockClient.storeToContinuum).toHaveBeenCalledWith('Important context', {
        tier: 'medium',
        tags: ['context'],
      });
      expect(result.id).toBe('entry-123');
    });

    it('should retrieve from continuum', async () => {
      mockClient.retrieveFromContinuum.mockResolvedValue({
        memories: [{ id: 'e1', content: 'context data', tier: 'medium' }],
        count: 1,
      });

      const result = await api.retrieveFromContinuum('context');

      expect(mockClient.retrieveFromContinuum).toHaveBeenCalledWith('context', undefined);
      expect(result.memories).toHaveLength(1);
      expect(result.count).toBe(1);
    });

    it('should retrieve continuum with options', async () => {
      mockClient.request.mockResolvedValue({
        memories: [{ id: 'e1', content: 'data' }],
        count: 5,
      });

      const result = await api.retrieveContinuum('user preferences', {
        tiers: ['fast', 'medium'],
        limit: 10,
        min_importance: 0.5,
      });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/continuum/retrieve', {
        params: {
          query: 'user preferences',
          limit: 10,
          min_importance: 0.5,
          tiers: 'fast,medium',
        },
      });
    });

    it('should get continuum stats', async () => {
      mockClient.getContinuumStats.mockResolvedValue({
        total_entries: 500,
        total_size_bytes: 256000,
        average_importance: 0.65,
      });

      const result = await api.continuumStats();

      expect(mockClient.getContinuumStats).toHaveBeenCalled();
      expect(result.total_entries).toBe(500);
    });

    it('should consolidate memory', async () => {
      mockClient.consolidateMemory.mockResolvedValue({ success: true });

      const result = await api.consolidate();

      expect(mockClient.consolidateMemory).toHaveBeenCalled();
      expect(result.success).toBe(true);
    });
  });

  // ===========================================================================
  // Maintenance Operations
  // ===========================================================================

  describe('Maintenance Operations', () => {
    it('should prune old entries', async () => {
      mockClient.request.mockResolvedValue({
        pruned_count: 150,
        freed_bytes: 153600,
        tiers_affected: ['fast', 'medium'],
      });

      const result = await api.prune({
        older_than_days: 30,
        min_importance: 0.1,
        tiers: ['fast', 'medium'],
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/prune', {
        body: {
          older_than_days: 30,
          min_importance: 0.1,
          tiers: ['fast', 'medium'],
        },
      });
      expect(result.pruned_count).toBe(150);
    });

    it('should prune with dry run', async () => {
      mockClient.request.mockResolvedValue({
        pruned_count: 200,
        freed_bytes: 0,
        tiers_affected: ['slow'],
      });

      const result = await api.prune({ dry_run: true });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/prune', {
        body: { dry_run: true },
      });
    });

    it('should compact memory', async () => {
      mockClient.request.mockResolvedValue({
        compacted: true,
        entries_merged: 50,
        space_saved_bytes: 25600,
      });

      const result = await api.compact({
        tier: 'slow',
        merge_threshold: 0.9,
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/compact', {
        body: { tier: 'slow', merge_threshold: 0.9 },
      });
      expect(result.entries_merged).toBe(50);
    });

    it('should sync memory', async () => {
      mockClient.request.mockResolvedValue({
        synced: true,
        entries_synced: 100,
        conflicts_resolved: 5,
        last_sync_at: '2024-01-01T00:00:00Z',
      });

      const result = await api.sync({
        target: 'all',
        conflict_resolution: 'latest_wins',
        tiers: ['medium', 'slow'],
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/sync', {
        body: {
          target: 'all',
          conflict_resolution: 'latest_wins',
          tiers: ['medium', 'slow'],
        },
      });
      expect(result.synced).toBe(true);
      expect(result.conflicts_resolved).toBe(5);
    });
  });

  // ===========================================================================
  // Tier-Specific Operations
  // ===========================================================================

  describe('Tier-Specific Operations', () => {
    it('should get entries from a specific tier', async () => {
      mockClient.request.mockResolvedValue({
        entries: [
          { key: 'k1', value: 'v1', tier: 'fast' },
          { key: 'k2', value: 'v2', tier: 'fast' },
        ],
        total: 100,
      });

      const result = await api.getTier('fast', { limit: 50 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/tier/fast', {
        params: { limit: 50 },
      });
      expect(result.entries).toHaveLength(2);
      expect(result.total).toBe(100);
    });

    it('should get glacial tier entries', async () => {
      mockClient.request.mockResolvedValue({
        entries: [{ key: 'archive-1', value: 'old data' }],
        total: 500,
      });

      const result = await api.getTier('glacial', { limit: 10, offset: 100 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/tier/glacial', {
        params: { limit: 10, offset: 100 },
      });
    });

    it('should promote a continuum entry to a target tier', async () => {
      mockClient.request.mockResolvedValue({
        success: true,
        previous_tier: 'fast',
      });

      const result = await api.promoteEntry('mem-123', 'slow');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/mem-123/promote', {
        body: { target_tier: 'slow' },
      });
      expect(result.success).toBe(true);
      expect(result.previous_tier).toBe('fast');
    });

    it('should URL-encode the memory ID when promoting', async () => {
      mockClient.request.mockResolvedValue({ success: false, previous_tier: null });

      await api.promoteEntry('id/with/slashes', 'medium');

      expect(mockClient.request).toHaveBeenCalledWith(
        'POST',
        '/api/v1/memory/id%2Fwith%2Fslashes/promote',
        { body: { target_tier: 'medium' } }
      );
    });

    it('should get tier analytics via GET with a days window', async () => {
      mockClient.request.mockResolvedValue({
        tier_stats: {},
        promotion_effectiveness: 0.8,
        learning_velocity: 0.2,
        total_entries: 42,
        total_hits: 100,
        overall_quality_impact: 0.1,
        recommendations: [],
        generated_at: '2026-07-16T00:00:00Z',
      });

      const result = await api.getTierAnalytics({ days: 7 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/analytics', {
        params: { days: 7 },
      });
      expect(result.promotion_effectiveness).toBe(0.8);
    });

    it('should get tier analytics with server-default window', async () => {
      mockClient.request.mockResolvedValue({
        tier_stats: {},
        promotion_effectiveness: 0,
        learning_velocity: 0,
        total_entries: 0,
        total_hits: 0,
        overall_quality_impact: 0,
        recommendations: [],
        generated_at: '2026-07-16T00:00:00Z',
      });

      await api.getTierAnalytics();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/memory/analytics', {
        params: {},
      });
    });

    it('should move entry between tiers', async () => {
      mockClient.request.mockResolvedValue({
        moved: true,
        key: 'important-data',
        from_tier: 'fast',
        to_tier: 'slow',
      });

      const result = await api.moveTier('important-data', 'fast', 'slow');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/important-data/move', {
        body: { from_tier: 'fast', to_tier: 'slow' },
      });
      expect(result.moved).toBe(true);
      expect(result.to_tier).toBe('slow');
    });

    it('should move entry with URL-encoded key', async () => {
      mockClient.request.mockResolvedValue({
        moved: true,
        key: 'key/with/slashes',
        from_tier: 'medium',
        to_tier: 'glacial',
      });

      const result = await api.moveTier('key/with/slashes', 'medium', 'glacial');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/memory/key%2Fwith%2Fslashes/move', {
        body: { from_tier: 'medium', to_tier: 'glacial' },
      });
    });
  });

  // ===========================================================================
  // Edge Cases
  // ===========================================================================

  describe('Edge Cases', () => {
    it('should handle empty search results', async () => {
      mockClient.searchMemory.mockResolvedValue({ entries: [] });

      const result = await api.search({ query: 'nonexistent' });

      expect(result.entries).toHaveLength(0);
    });

    it('should store complex nested values', async () => {
      mockClient.storeMemory.mockResolvedValue({ stored: true, tier: 'medium' });

      const complexValue = {
        nested: {
          deeply: {
            value: [1, 2, 3],
            metadata: { type: 'array' },
          },
        },
      };

      const result = await api.store('complex-key', complexValue);

      expect(mockClient.storeMemory).toHaveBeenCalledWith('complex-key', complexValue, undefined);
      expect(result.stored).toBe(true);
    });

    it('should handle store with all tier options', async () => {
      const tiers = ['fast', 'medium', 'slow', 'glacial'] as const;

      for (const tier of tiers) {
        mockClient.storeMemory.mockResolvedValue({ stored: true, tier });
        const result = await api.store(`key-${tier}`, 'value', { tier });
        expect(result.tier).toBe(tier);
      }
    });
  });
});
