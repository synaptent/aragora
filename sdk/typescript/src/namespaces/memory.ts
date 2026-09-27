/**
 * Memory Namespace API
 *
 * Provides a namespaced interface for memory management operations:
 * - Core CRUD operations (store, retrieve, update, delete)
 * - Continuum tier management (fast/medium/slow/glacial operations)
 * - Memory search/query (semantic search, filtered queries)
 * - Cross-debate memory (institutional knowledge)
 * - Memory export/import (backup/restore)
 * - Memory snapshots (point-in-time recovery)
 * - Memory analytics/stats
 * - Context management
 * - Maintenance operations (prune, compact, sync, vacuum)
 *
 * NOTE: Several "advanced" methods below (context, cross-debate,
 * export/import, snapshots, prune/compact/sync/vacuum, rebuild-index,
 * semantic search) target routes that are declared in the memory handler's
 * ROUTES list but never dispatched, so they always fail against a live
 * server. They are kept for backward compatibility and marked @deprecated;
 * prefer the documented working methods (search, tiers/tier stats,
 * continuum retrieve/consolidate, critiques).
 */

import type {
  MemoryEntry,
  MemoryStats,
  MemoryTier,
  MemoryTierStats,
  MemorySearchParams,
  CritiqueEntry,
  ContinuumStoreOptions,
  ContinuumStoreResult,
  ContinuumRetrieveOptions,
  PaginationParams,
} from '../types';

/**
 * Memory tier type alias.
 */
export type MemoryTierType = 'fast' | 'medium' | 'slow' | 'glacial';

/**
 * Conflict resolution strategy.
 */
export type ConflictResolution = 'latest_wins' | 'merge' | 'manual';

/**
 * Sort order type.
 */
export type SortOrder = 'asc' | 'desc';

/**
 * Pressure level type.
 */
export type PressureLevel = 'low' | 'medium' | 'high' | 'critical';

/**
 * Options for storing memory entries.
 */
export interface MemoryStoreOptions {
  /** Key for the memory entry */
  key: string;
  /** Value to store */
  value: unknown;
  /** Optional TTL in seconds */
  ttl?: number;
  /** Optional tags for categorization */
  tags?: string[];
  /** Optional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Options for retrieving memory entries.
 */
export interface MemoryRetrieveOptions {
  /** Filter by memory tier */
  tier?: MemoryTier;
  /** Filter by tags */
  tags?: string[];
  /** Maximum number of results */
  limit?: number;
}

/**
 * Memory tier statistics response.
 */
export interface MemoryTierStatsResponse {
  fast: { count: number; size_bytes: number; oldest?: string };
  medium: { count: number; size_bytes: number; oldest?: string };
  slow: { count: number; size_bytes: number; oldest?: string };
  glacial: { count: number; size_bytes: number; oldest?: string };
}

/**
 * Memory archive statistics response.
 */
export interface MemoryArchiveStatsResponse {
  total_archived: number;
  archive_size_bytes: number;
  oldest_entry?: string;
  newest_entry?: string;
  compression_ratio?: number;
}

/**
 * Memory pressure response.
 */
export interface MemoryPressureResponse {
  utilization: number;
  pressure_level: PressureLevel;
  recommendations?: string[];
  by_tier?: Record<string, { utilization: number; entries: number }>;
}

/**
 * Memory context response.
 */
export interface MemoryContext {
  context_id: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
  expires_at?: string;
}

/**
 * Prune result response.
 */
export interface PruneResult {
  pruned_count: number;
  freed_bytes: number;
  tiers_affected: string[];
}

/**
 * Compact result response.
 */
export interface CompactResult {
  compacted: boolean;
  entries_merged: number;
  space_saved_bytes: number;
}

/**
 * Sync result response.
 */
export interface SyncResult {
  synced: boolean;
  entries_synced: number;
  conflicts_resolved: number;
  last_sync_at: string;
}

/**
 * Query options for memory.
 */
export interface MemoryQueryOptions {
  filter?: Record<string, unknown>;
  sort_by?: string;
  sort_order?: SortOrder;
  limit?: number;
  offset?: number;
  include_metadata?: boolean;
}

/**
 * Semantic search options.
 */
export interface SemanticSearchOptions {
  /** Tiers to search (all if not specified) */
  tiers?: MemoryTierType[];
  /** Maximum results */
  limit?: number;
  /** Minimum similarity threshold (0.0-1.0) */
  min_similarity?: number;
  /** Whether to include embedding vectors */
  include_embeddings?: boolean;
}

/**
 * Semantic search result.
 */
export interface SemanticSearchResult {
  entries: Array<MemoryEntry & { similarity: number }>;
  total: number;
  query_time_ms?: number;
}

/**
 * Cross-debate memory entry.
 */
export interface CrossDebateEntry {
  id: string;
  content: string;
  debate_id: string;
  topic?: string;
  conclusion?: string;
  confidence: number;
  relevance?: number;
  created_at: string;
  metadata?: Record<string, unknown>;
}

/**
 * Cross-debate memory response.
 */
export interface CrossDebateResponse {
  entries: CrossDebateEntry[];
  total: number;
}

/**
 * Memory export options.
 */
export interface MemoryExportOptions {
  /** Tiers to export (all if not specified) */
  tiers?: MemoryTierType[];
  /** Filter by tags */
  tags?: string[];
  /** Export format */
  format?: 'json' | 'msgpack';
  /** Include entry metadata */
  include_metadata?: boolean;
}

/**
 * Memory export result.
 */
export interface MemoryExportResult {
  export_id?: string;
  data?: unknown;
  download_url?: string;
  format: string;
  entries_count: number;
  size_bytes?: number;
  created_at: string;
}

/**
 * Memory import options.
 */
export interface MemoryImportOptions {
  /** Whether to overwrite existing entries */
  overwrite?: boolean;
  /** Force all entries to specific tier */
  target_tier?: MemoryTierType;
}

/**
 * Memory import result.
 */
export interface MemoryImportResult {
  imported_count: number;
  skipped_count: number;
  overwritten_count: number;
  errors?: string[];
}

/**
 * Memory snapshot.
 */
export interface MemorySnapshot {
  id: string;
  name?: string;
  description?: string;
  created_at: string;
  size_bytes: number;
  entries_count: number;
  tiers_included: MemoryTierType[];
  metadata?: Record<string, unknown>;
}

/**
 * Memory analytics response.
 */
export interface MemoryAnalyticsResponse {
  period_start?: string;
  period_end?: string;
  granularity: string;
  data_points: Array<{
    timestamp: string;
    entries_count: number;
    storage_bytes: number;
    operations: {
      stores: number;
      retrieves: number;
      deletes: number;
    };
  }>;
}

/**
 * Tier analytics response from GET /api/v1/memory/analytics.
 *
 * Matches `TierAnalytics.to_dict()` served by MemoryAnalyticsHandler.
 */
export interface TierAnalyticsResponse {
  tier_stats: Record<string, {
    tier: string;
    entries: number;
    total_hits: number;
    avg_hits: number;
    total_quality_impact: number;
    avg_quality_impact: number;
    promotions_in: number;
    promotions_out: number;
    demotions_in: number;
    demotions_out: number;
  }>;
  promotion_effectiveness: number;
  learning_velocity: number;
  total_entries: number;
  total_hits: number;
  overall_quality_impact: number;
  recommendations: string[];
  generated_at: string;
}

/**
 * Vacuum result response.
 */
export interface VacuumResult {
  vacuumed: boolean;
  space_reclaimed_bytes: number;
  duration_ms: number;
}

/**
 * Rebuild index result response.
 */
export interface RebuildIndexResult {
  rebuilt: boolean;
  indexes_rebuilt: number;
  duration_ms: number;
  tier?: MemoryTierType;
}

/**
 * Interface for the internal client methods used by MemoryAPI.
 */
interface MemoryClientInterface {
  storeMemory(key: string, value: unknown, options?: {
    tier?: MemoryTierType;
    importance?: number;
    tags?: string[];
    ttl_seconds?: number;
    metadata?: Record<string, unknown>;
  }): Promise<{ stored: boolean; tier: string }>;
  retrieveMemory(key: string, options?: {
    tier?: MemoryTierType;
  }): Promise<{ value: unknown; tier: string; metadata?: Record<string, unknown> } | null>;
  deleteMemory(key: string, tier?: MemoryTierType): Promise<{ deleted: boolean }>;
  storeMemoryEntry(content: string, options?: {
    tier?: MemoryTierType;
    importance?: number;
  }): Promise<{ id: string; tier: string }>;
  deleteMemoryEntry(memoryId: string): Promise<{ success: boolean; message: string }>;
  getMemoryStats(): Promise<MemoryStats>;
  searchMemory(params: MemorySearchParams): Promise<{ entries: MemoryEntry[] }>;
  getMemoryTiers(): Promise<{ tiers: MemoryTierStats[] }>;
  getMemoryCritiques(options?: PaginationParams): Promise<{ critiques: CritiqueEntry[] }>;
  storeToContinuum(content: string, options?: ContinuumStoreOptions): Promise<ContinuumStoreResult>;
  retrieveFromContinuum(query: string, options?: ContinuumRetrieveOptions): Promise<{ memories: MemoryEntry[]; count: number }>;
  getContinuumStats(): Promise<MemoryStats>;
  consolidateMemory(): Promise<{ success: boolean }>;
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; body?: unknown; json?: unknown }
  ): Promise<T>;
}

/**
 * Memory API namespace.
 *
 * Provides methods for managing memory:
 * - Storing and retrieving key-value entries
 * - Managing memory tiers (fast, medium, slow, glacial)
 * - Searching memory content
 * - Working with the continuum memory system
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Store a memory entry
 * const { id } = await client.memory.storeEntry('User prefers dark theme', { tier: 'fast' });
 *
 * // Retrieve memories by query
 * const { memories } = await client.memory.retrieveContinuum('user preferences');
 *
 * // Search memory
 * const results = await client.memory.search('theme settings');
 *
 * // Get memory statistics
 * const stats = await client.memory.stats();
 * ```
 */
export class MemoryAPI {
  constructor(private client: MemoryClientInterface) {}

  /**
   * Store a value in memory.
   *
   * @deprecated The server does not implement a key/value memory API;
   * POST /api/v1/memory/store rejects this payload with 400. Use
   * {@link storeEntry} instead.
   */
  async store(
    key: string,
    value: unknown,
    options?: {
      tier?: 'fast' | 'medium' | 'slow' | 'glacial';
      importance?: number;
      tags?: string[];
      ttl_seconds?: number;
    }
  ): Promise<{ stored: boolean; tier: string }> {
    return this.client.storeMemory(key, value, options);
  }

  /**
   * Store a new memory entry in continuum memory.
   *
   * Matches the server contract for POST /api/v1/memory/store
   * ({ content, tier?, importance? } -> { id, tier }).
   */
  async storeEntry(
    content: string,
    options?: {
      tier?: 'fast' | 'medium' | 'slow' | 'glacial';
      importance?: number;
    }
  ): Promise<{ id: string; tier: string }> {
    return this.client.request('POST', '/api/v1/memory/store', {
      body: { content, ...options },
    });
  }

  /**
   * Retrieve a value from memory by key.
   *
   * @deprecated The server does not implement GET /api/v1/memory/retrieve,
   * so this always resolves to `null`. Use {@link retrieveContinuum} to
   * query continuum memory instead.
   */
  async retrieve(
    key: string,
    options?: { tier?: 'fast' | 'medium' | 'slow' | 'glacial' }
  ): Promise<{ value: unknown; tier: string; metadata?: Record<string, unknown> } | null> {
    return this.client.retrieveMemory(key, options);
  }

  /**
   * Delete a memory entry by key.
   *
   * @deprecated The server does not implement DELETE /api/v1/memory/delete,
   * so this always rejects with a 404. Use {@link deleteEntry} with the
   * entry ID returned by {@link storeEntry} instead.
   */
  async delete(
    key: string,
    tier?: 'fast' | 'medium' | 'slow' | 'glacial'
  ): Promise<{ deleted: boolean }> {
    return this.client.deleteMemory(key, tier);
  }

  /**
   * Delete a continuum memory entry by ID.
   *
   * Matches the server contract for DELETE /api/v1/memory/continuum/{id}
   * ({ success, message }; 404 if the entry does not exist).
   */
  async deleteEntry(memoryId: string): Promise<{ success: boolean; message: string }> {
    return this.client.request(
      'DELETE',
      `/api/v1/memory/continuum/${encodeURIComponent(memoryId)}`
    );
  }

  /**
   * Get memory system statistics.
   *
   * @deprecated No memory-handler branch serves GET /api/v1/memory/stats.
   * The request is routed to the analytics handler, which requires the
   * `analytics:read` permission and returns only
   * `{ stats: { embeddings_db, insights_db, continuum_memory } }` — database
   * file-existence booleans, not the declared {@link MemoryStats} shape.
   * Use {@link tiers} or {@link getTierStats} for real memory metrics.
   */
  async stats(): Promise<MemoryStats> {
    return this.client.getMemoryStats();
  }

  /**
   * Search memory entries by query.
   */
  async search(params: MemorySearchParams): Promise<{ entries: MemoryEntry[] }> {
    return this.client.searchMemory(params);
  }

  /**
   * Get information about memory tiers.
   */
  async tiers(): Promise<{ tiers: MemoryTierStats[] }> {
    return this.client.getMemoryTiers();
  }

  /**
   * Get stored critiques from memory.
   */
  async critiques(options?: PaginationParams): Promise<{ critiques: CritiqueEntry[] }> {
    return this.client.getMemoryCritiques(options);
  }

  /**
   * Store content in the continuum memory system.
   *
   * @deprecated No handler serves POST /api/memory/continuum/store, so this
   * method always rejects with an HTTP 500 (`handler_no_result`). Use
   * {@link storeEntry} (POST /api/v1/memory/store), which returns
   * `{ id, tier }` — without the `created_at` field declared here.
   */
  async storeToContinuum(
    content: string,
    options?: ContinuumStoreOptions
  ): Promise<ContinuumStoreResult> {
    return this.client.storeToContinuum(content, options);
  }

  /**
   * Retrieve content from the continuum memory system.
   */
  async retrieveFromContinuum(
    query: string,
    options?: ContinuumRetrieveOptions
  ): Promise<{ memories: MemoryEntry[]; count: number }> {
    return this.client.retrieveFromContinuum(query, options);
  }

  /**
   * Get continuum memory statistics.
   *
   * @deprecated GET /api/memory/continuum/stats has no dispatch branch in
   * the memory handler, so this method always fails against a live server
   * (HTTP 500 handler_no_result). Use {@link getTierStats} or {@link tiers}
   * instead.
   */
  async continuumStats(): Promise<MemoryStats> {
    return this.client.getContinuumStats();
  }

  /**
   * Consolidate memory by archiving old entries.
   */
  async consolidate(): Promise<{ success: boolean }> {
    return this.client.consolidateMemory();
  }

  // ===========================================================================
  // Update Operations
  // ===========================================================================

  /**
   * Update an existing memory entry.
   *
   * @deprecated No memory handler implements PUT, but MemoryHandler still
   * matches the path, so PUT /api/v1/memory/{key} always rejects with an
   * HTTP 500 (`handler_no_result`). The server has no key/value update API;
   * store a new entry via POST /api/v1/memory/store instead.
   *
   * @param key - The key of the entry to update
   * @param value - The new value
   * @param options - Update options
   */
  async update(
    key: string,
    value: unknown,
    options?: {
      tier?: 'fast' | 'medium' | 'slow' | 'glacial';
      merge?: boolean;
      tags?: string[];
    }
  ): Promise<{ updated: boolean; tier: string }> {
    return this.client.request('PUT', `/api/v1/memory/${encodeURIComponent(key)}`, {
      body: { value, ...options },
    });
  }

  // ===========================================================================
  // Query Operations
  // ===========================================================================

  /**
   * Query memory entries with advanced filtering.
   *
   * @deprecated POST /api/v1/memory/query is declared in the handler's ROUTES
   * list but never dispatched, so this method always rejects with an HTTP 500
   * (`handler_no_result`). Use {@link search} (GET /api/v1/memory/search) or
   * {@link retrieveContinuum}.
   *
   * @param options - Query options including filters, sorting, and pagination
   */
  async query(options: MemoryQueryOptions): Promise<{ entries: MemoryEntry[]; total: number }> {
    return this.client.request('POST', '/api/v1/memory/query', {
      body: options,
    });
  }

  // ===========================================================================
  // Context Management
  // ===========================================================================

  /**
   * Get the current memory context.
   *
   * @deprecated GET /api/v1/memory/context is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). The server has no
   * memory-context store; there is no replacement endpoint.
   *
   * @param contextId - Optional context ID (defaults to current session)
   *
   * @example
   * ```typescript
   * const context = await client.memory.getContext();
   * console.log(`Context data:`, context.data);
   * ```
   */
  async getContext(contextId?: string): Promise<MemoryContext> {
    const params: Record<string, unknown> = {};
    if (contextId) {
      params.context_id = contextId;
    }
    return this.client.request('GET', '/api/v1/memory/context', { params });
  }

  /**
   * Set or update the memory context.
   *
   * @deprecated POST /api/v1/memory/context is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). The server has no
   * memory-context store; there is no replacement endpoint.
   *
   * @param data - Context data to set
   * @param options - Context options
   *
   * @example
   * ```typescript
   * await client.memory.setContext(
   *   { user_id: '123', session_id: 'abc' },
   *   { ttl_seconds: 3600 }
   * );
   * ```
   */
  async setContext(
    data: Record<string, unknown>,
    options?: { context_id?: string; ttl_seconds?: number }
  ): Promise<MemoryContext> {
    return this.client.request('POST', '/api/v1/memory/context', {
      body: { data, ...options },
    });
  }

  // ===========================================================================
  // Tier Statistics (matching Python SDK)
  // ===========================================================================

  /**
   * Get statistics for all memory tiers.
   *
   * Matches Python SDK's `get_tier_stats()` method.
   *
   * @example
   * ```typescript
   * const stats = await client.memory.getTierStats();
   * console.log(`Fast tier: ${stats.fast.count} entries`);
   * console.log(`Slow tier: ${stats.slow.count} entries`);
   * ```
   */
  async getTierStats(): Promise<MemoryTierStatsResponse> {
    return this.client.request('GET', '/api/v1/memory/tier-stats');
  }

  /**
   * Get archive statistics.
   *
   * Matches Python SDK's `get_archive_stats()` method.
   *
   * @example
   * ```typescript
   * const stats = await client.memory.getArchiveStats();
   * console.log(`Total archived: ${stats.total_archived}`);
   * console.log(`Archive size: ${stats.archive_size_bytes} bytes`);
   * ```
   */
  async getArchiveStats(): Promise<MemoryArchiveStatsResponse> {
    return this.client.request('GET', '/api/v1/memory/archive-stats');
  }

  /**
   * Get memory pressure and utilization metrics.
   *
   * Matches Python SDK's `get_pressure()` method.
   *
   * @example
   * ```typescript
   * const pressure = await client.memory.getPressure();
   * if (pressure.pressure_level === 'critical') {
   *   console.log('Memory pressure is critical!');
   *   console.log('Recommendations:', pressure.recommendations);
   * }
   * ```
   */
  async getPressure(): Promise<MemoryPressureResponse> {
    return this.client.request('GET', '/api/v1/memory/pressure');
  }

  /**
   * List all memory tiers with detailed statistics.
   *
   * Matches Python SDK's `list_tiers()` method.
   * This is an alias for `tiers()` but matches the Python SDK naming.
   *
   * @example
   * ```typescript
   * const { tiers } = await client.memory.listTiers();
   * for (const tier of tiers) {
   *   console.log(`${tier.name}: ${tier.entry_count} entries`);
   * }
   * ```
   */
  async listTiers(): Promise<{ tiers: MemoryTierStats[] }> {
    return this.client.request('GET', '/api/v1/memory/tiers');
  }

  /**
   * List critique store entries.
   *
   * Matches Python SDK's `list_critiques()` method.
   *
   * @param options - Filter options
   *
   * @example
   * ```typescript
   * const { critiques } = await client.memory.listCritiques({
   *   agent: 'claude',
   *   limit: 20,
   * });
   * ```
   */
  async listCritiques(options?: {
    agent?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ critiques: CritiqueEntry[] }> {
    return this.client.request('GET', '/api/v1/memory/critiques', {
      params: options as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Continuum Operations (matching Python SDK)
  // ===========================================================================

  /**
   * Retrieve memories from the continuum.
   *
   * Matches Python SDK's `retrieve_continuum()` method and the server
   * contract for GET /api/v1/memory/continuum/retrieve, which responds with
   * `{ memories, count, query, tiers }` (not `{ entries, total }`).
   *
   * @param query - Search query
   * @param options - Retrieval options
   *
   * @example
   * ```typescript
   * const { memories, count } = await client.memory.retrieveContinuum('user preferences', {
   *   tiers: ['fast', 'medium'],
   *   limit: 10,
   *   min_importance: 0.5,
   * });
   * ```
   */
  async retrieveContinuum(
    query: string = '',
    options?: {
      tiers?: Array<'fast' | 'medium' | 'slow' | 'glacial'>;
      limit?: number;
      min_importance?: number;
    }
  ): Promise<{ memories: MemoryEntry[]; count: number }> {
    const params: Record<string, unknown> = {
      query,
      limit: options?.limit ?? 10,
      min_importance: options?.min_importance ?? 0.0,
    };
    if (options?.tiers) {
      params.tiers = options.tiers.join(',');
    }
    return this.client.request('GET', '/api/v1/memory/continuum/retrieve', { params });
  }

  // ===========================================================================
  // Maintenance Operations
  // ===========================================================================

  /**
   * Prune old or low-importance memory entries.
   *
   * @deprecated POST /api/v1/memory/prune is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). Expired entries are
   * cleaned via POST /api/v1/memory/continuum/cleanup; see also
   * {@link consolidate}.
   *
   * @param options - Prune options
   *
   * @example
   * ```typescript
   * const result = await client.memory.prune({
   *   older_than_days: 30,
   *   min_importance: 0.1,
   *   tiers: ['fast', 'medium'],
   * });
   * console.log(`Pruned ${result.pruned_count} entries`);
   * console.log(`Freed ${result.freed_bytes} bytes`);
   * ```
   */
  async prune(options?: {
    older_than_days?: number;
    min_importance?: number;
    tiers?: Array<'fast' | 'medium' | 'slow' | 'glacial'>;
    dry_run?: boolean;
  }): Promise<PruneResult> {
    return this.client.request('POST', '/api/v1/memory/prune', {
      body: options,
    });
  }

  /**
   * Compact memory storage by merging related entries.
   *
   * @deprecated POST /api/v1/memory/compact is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). Use
   * {@link consolidate} for the supported maintenance operation.
   *
   * @param options - Compact options
   *
   * @example
   * ```typescript
   * const result = await client.memory.compact({
   *   tier: 'slow',
   *   merge_threshold: 0.9,
   * });
   * console.log(`Merged ${result.entries_merged} entries`);
   * console.log(`Saved ${result.space_saved_bytes} bytes`);
   * ```
   */
  async compact(options?: {
    tier?: 'fast' | 'medium' | 'slow' | 'glacial';
    merge_threshold?: number;
  }): Promise<CompactResult> {
    return this.client.request('POST', '/api/v1/memory/compact', {
      body: options,
    });
  }

  /**
   * Synchronize memory across distributed systems.
   *
   * @deprecated POST /api/v1/memory/sync is declared in the memory handler's
   * ROUTES list but never dispatched, so this method always fails against a
   * live server (HTTP 500 handler_no_result). Use {@link consolidate} for
   * the supported maintenance operation.
   *
   * @param options - Sync options
   *
   * @example
   * ```typescript
   * const result = await client.memory.sync({
   *   target: 'all',
   *   conflict_resolution: 'latest_wins',
   * });
   * if (result.synced) {
   *   console.log(`Synced ${result.entries_synced} entries`);
   * }
   * ```
   */
  async sync(options?: {
    target?: string;
    conflict_resolution?: 'latest_wins' | 'merge' | 'manual';
    tiers?: Array<'fast' | 'medium' | 'slow' | 'glacial'>;
  }): Promise<SyncResult> {
    return this.client.request('POST', '/api/v1/memory/sync', {
      body: options,
    });
  }

  // ===========================================================================
  // Tier-Specific Operations
  // ===========================================================================

  /**
   * Get entries from a specific tier.
   *
   * @deprecated GET /api/v1/memory/tier/{tier} is declared in the handler's
   * ROUTES list but never dispatched, so this method always rejects with an
   * HTTP 500 (`handler_no_result`). Use {@link listTiers} for tier stats, or
   * {@link retrieveContinuum} with a `tiers` filter for entries.
   *
   * @param tier - The memory tier
   * @param options - Retrieval options
   */
  async getTier(
    tier: 'fast' | 'medium' | 'slow' | 'glacial',
    options?: { limit?: number; offset?: number }
  ): Promise<{ entries: MemoryEntry[]; total: number }> {
    return this.client.request('GET', `/api/v1/memory/tier/${tier}`, {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Move an entry between tiers.
   *
   * @deprecated POST /api/v1/memory/{key}/move is declared in the handler's
   * ROUTES list but never dispatched, so this method always rejects with an
   * HTTP 500 (`handler_no_result`). The only server-side tier mutation is
   * promotion — use {@link promoteEntry}.
   *
   * @param key - The entry key
   * @param fromTier - Source tier
   * @param toTier - Destination tier
   */
  async moveTier(
    key: string,
    fromTier: MemoryTierType,
    toTier: MemoryTierType
  ): Promise<{ moved: boolean; key: string; from_tier: string; to_tier: string }> {
    return this.client.request('POST', `/api/v1/memory/${encodeURIComponent(key)}/move`, {
      body: { from_tier: fromTier, to_tier: toTier },
    });
  }

  // ===========================================================================
  // Semantic Search (matching Python SDK)
  // ===========================================================================

  /**
   * Perform semantic search across memory entries.
   *
   * Matches Python SDK's `semantic_search()` method.
   *
   * @deprecated POST /api/v1/memory/semantic-search is declared in the
   * memory handler's ROUTES list but never dispatched, so this method always
   * fails against a live server (HTTP 500 handler_no_result). Use
   * {@link search} or {@link searchIndex} (with `use_hybrid`) instead.
   *
   * @param query - Natural language query
   * @param options - Search options
   *
   * @example
   * ```typescript
   * const results = await client.memory.semanticSearch('previous decisions about pricing', {
   *   tiers: ['slow', 'glacial'],
   *   limit: 10,
   *   min_similarity: 0.7,
   * });
   * for (const entry of results.entries) {
   *   console.log(`${entry.content} (similarity: ${entry.similarity})`);
   * }
   * ```
   */
  async semanticSearch(
    query: string,
    options?: SemanticSearchOptions
  ): Promise<SemanticSearchResult> {
    const body: Record<string, unknown> = {
      query,
      limit: options?.limit ?? 10,
      min_similarity: options?.min_similarity ?? 0.7,
      include_embeddings: options?.include_embeddings ?? false,
    };
    if (options?.tiers) {
      body.tiers = options.tiers;
    }
    return this.client.request('POST', '/api/v1/memory/semantic-search', { body });
  }

  // ===========================================================================
  // Cross-Debate Memory (Institutional Knowledge)
  // ===========================================================================

  /**
   * Get cross-debate institutional knowledge.
   *
   * Matches Python SDK's `get_cross_debate()` method.
   *
   * @deprecated GET /api/v1/memory/cross-debate is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). Cross-debate memory
   * is injected automatically during debates (`enable_cross_debate_memory`);
   * there is no HTTP endpoint.
   *
   * @param options - Retrieval options
   *
   * @example
   * ```typescript
   * const result = await client.memory.getCrossDebate({
   *   topic: 'pricing strategy',
   *   limit: 10,
   *   min_relevance: 0.5,
   * });
   * for (const entry of result.entries) {
   *   console.log(`From debate ${entry.debate_id}: ${entry.content}`);
   * }
   * ```
   */
  async getCrossDebate(options?: {
    topic?: string;
    limit?: number;
    min_relevance?: number;
  }): Promise<CrossDebateResponse> {
    const params: Record<string, unknown> = {
      limit: options?.limit ?? 10,
      min_relevance: options?.min_relevance ?? 0.5,
    };
    if (options?.topic) {
      params.topic = options.topic;
    }
    return this.client.request('GET', '/api/v1/memory/cross-debate', { params });
  }

  /**
   * Store cross-debate knowledge from a debate outcome.
   *
   * Matches Python SDK's `store_cross_debate()` method.
   *
   * @deprecated POST /api/v1/memory/cross-debate is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). Cross-debate memory
   * is recorded automatically during debates; there is no HTTP endpoint.
   *
   * @param content - Knowledge content
   * @param debateId - Source debate ID
   * @param options - Storage options
   *
   * @example
   * ```typescript
   * const result = await client.memory.storeCrossDebate(
   *   'Key insight about pricing: value-based pricing works best for enterprise',
   *   'debate-123',
   *   {
   *     topic: 'pricing',
   *     conclusion: 'Value-based pricing recommended',
   *     confidence: 0.85,
   *   }
   * );
   * ```
   */
  async storeCrossDebate(
    content: string,
    debateId: string,
    options?: {
      topic?: string;
      conclusion?: string;
      confidence?: number;
      metadata?: Record<string, unknown>;
    }
  ): Promise<{ id: string; stored: boolean }> {
    const body: Record<string, unknown> = {
      content,
      debate_id: debateId,
    };
    if (options?.topic) body.topic = options.topic;
    if (options?.conclusion) body.conclusion = options.conclusion;
    if (options?.confidence !== undefined) body.confidence = options.confidence;
    if (options?.metadata) body.metadata = options.metadata;
    return this.client.request('POST', '/api/v1/memory/cross-debate', { body });
  }

  /**
   * Inject institutional knowledge into a debate.
   *
   * Matches Python SDK's `inject_institutional()` method.
   *
   * @deprecated POST /api/v1/memory/cross-debate/inject is declared in the
   * memory handler's ROUTES list but never dispatched, so this method always
   * fails against a live server (HTTP 500 handler_no_result). Cross-debate
   * memory is injected automatically during debates
   * (`enable_cross_debate_memory`); there is no HTTP endpoint.
   *
   * @param debateId - Target debate ID
   * @param options - Injection options
   *
   * @example
   * ```typescript
   * const result = await client.memory.injectInstitutional('debate-456', {
   *   topic: 'pricing strategy',
   *   max_entries: 5,
   * });
   * console.log(`Injected ${result.injected_count} knowledge entries`);
   * ```
   */
  async injectInstitutional(
    debateId: string,
    options?: {
      topic?: string;
      max_entries?: number;
    }
  ): Promise<{ debate_id: string; injected_count: number }> {
    const body: Record<string, unknown> = {
      debate_id: debateId,
      max_entries: options?.max_entries ?? 5,
    };
    if (options?.topic) body.topic = options.topic;
    return this.client.request('POST', '/api/v1/memory/cross-debate/inject', { body });
  }

  // ===========================================================================
  // Export/Import (Backup/Restore)
  // ===========================================================================

  /**
   * Export memory entries for backup.
   *
   * Matches Python SDK's `export_memory()` method.
   *
   * @deprecated POST /api/v1/memory/export is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). There is no
   * replacement endpoint.
   *
   * @param options - Export options
   *
   * @example
   * ```typescript
   * const result = await client.memory.exportMemory({
   *   tiers: ['slow', 'glacial'],
   *   format: 'json',
   *   include_metadata: true,
   * });
   * console.log(`Exported ${result.entries_count} entries`);
   * ```
   */
  async exportMemory(options?: MemoryExportOptions): Promise<MemoryExportResult> {
    const body: Record<string, unknown> = {
      format: options?.format ?? 'json',
      include_metadata: options?.include_metadata ?? true,
    };
    if (options?.tiers) body.tiers = options.tiers;
    if (options?.tags) body.tags = options.tags;
    return this.client.request('POST', '/api/v1/memory/export', { body });
  }

  /**
   * Import memory entries from backup.
   *
   * Matches Python SDK's `import_memory()` method.
   *
   * @deprecated POST /api/v1/memory/import is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). There is no
   * replacement endpoint.
   *
   * @param data - Memory data to import
   * @param options - Import options
   *
   * @example
   * ```typescript
   * const result = await client.memory.importMemory(backupData, {
   *   overwrite: false,
   *   target_tier: 'slow',
   * });
   * console.log(`Imported ${result.imported_count} entries`);
   * ```
   */
  async importMemory(
    data: Record<string, unknown> | Array<Record<string, unknown>>,
    options?: MemoryImportOptions
  ): Promise<MemoryImportResult> {
    const body: Record<string, unknown> = {
      data,
      overwrite: options?.overwrite ?? false,
    };
    if (options?.target_tier) body.target_tier = options.target_tier;
    return this.client.request('POST', '/api/v1/memory/import', { body });
  }

  // ===========================================================================
  // Snapshots (Point-in-Time Recovery)
  // ===========================================================================

  /**
   * Create a point-in-time snapshot of memory.
   *
   * Matches Python SDK's `create_snapshot()` method.
   *
   * @deprecated POST /api/v1/memory/snapshots is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). There is no
   * replacement endpoint.
   *
   * @param options - Snapshot options
   *
   * @example
   * ```typescript
   * const snapshot = await client.memory.createSnapshot({
   *   name: 'pre-migration-backup',
   *   description: 'Backup before schema migration',
   * });
   * console.log(`Created snapshot ${snapshot.id}`);
   * ```
   */
  async createSnapshot(options?: {
    name?: string;
    description?: string;
  }): Promise<MemorySnapshot> {
    const body: Record<string, unknown> = {};
    if (options?.name) body.name = options.name;
    if (options?.description) body.description = options.description;
    return this.client.request('POST', '/api/v1/memory/snapshots', { body });
  }

  /**
   * List available memory snapshots.
   *
   * Matches Python SDK's `list_snapshots()` method.
   *
   * @deprecated GET /api/v1/memory/snapshots is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). There is no
   * replacement endpoint.
   *
   * @param options - Pagination options
   *
   * @example
   * ```typescript
   * const result = await client.memory.listSnapshots({ limit: 10 });
   * for (const snapshot of result.snapshots) {
   *   console.log(`${snapshot.name}: ${snapshot.entries_count} entries`);
   * }
   * ```
   */
  async listSnapshots(options?: {
    limit?: number;
    offset?: number;
  }): Promise<{ snapshots: MemorySnapshot[]; total: number }> {
    const params: Record<string, unknown> = {
      limit: options?.limit ?? 20,
      offset: options?.offset ?? 0,
    };
    return this.client.request('GET', '/api/v1/memory/snapshots', { params });
  }

  /**
   * Restore memory from a snapshot.
   *
   * Matches Python SDK's `restore_snapshot()` method.
   *
   * @deprecated POST /api/v1/memory/snapshots/{id}/restore is declared in
   * the memory handler's ROUTES list but never dispatched, so this method
   * always fails against a live server (HTTP 500 handler_no_result). There
   * is no replacement endpoint.
   *
   * @param snapshotId - Snapshot ID to restore
   * @param options - Restore options
   *
   * @example
   * ```typescript
   * const result = await client.memory.restoreSnapshot('snapshot-123', {
   *   overwrite: true,
   * });
   * if (result.restored) {
   *   console.log('Memory restored successfully');
   * }
   * ```
   */
  async restoreSnapshot(
    snapshotId: string,
    options?: { overwrite?: boolean }
  ): Promise<{ restored: boolean; snapshot_id: string; entries_restored: number }> {
    const body: Record<string, unknown> = {
      overwrite: options?.overwrite ?? false,
    };
    return this.client.request('POST', `/api/v1/memory/snapshots/${snapshotId}/restore`, { body });
  }

  /**
   * Delete a memory snapshot.
   *
   * Matches Python SDK's `delete_snapshot()` method.
   *
   * @deprecated DELETE /api/v1/memory/snapshots/{id} has no dispatch branch
   * in the memory handler (DELETE is only served for
   * /api/v1/memory/continuum/{id}), so this method always fails against a
   * live server (HTTP 500 handler_no_result). There is no replacement
   * endpoint.
   *
   * @param snapshotId - Snapshot ID to delete
   *
   * @example
   * ```typescript
   * const result = await client.memory.deleteSnapshot('snapshot-123');
   * if (result.deleted) {
   *   console.log('Snapshot deleted');
   * }
   * ```
   */
  async deleteSnapshot(snapshotId: string): Promise<{ deleted: boolean; snapshot_id: string }> {
    return this.client.request('DELETE', `/api/v1/memory/snapshots/${snapshotId}`);
  }

  // ===========================================================================
  // Tier Promotion/Demotion
  // ===========================================================================

  /**
   * Promote an entry to a faster tier.
   *
   * @deprecated The promote handler requires `{ target_tier }` in the body and
   * rejects this method's `{ reason }` payload with a 400. It also returns
   * `{ success, previous_tier }`, not the shape declared here. Use
   * {@link promoteEntry} instead.
   *
   * @param key - The entry key
   * @param options - Promotion options
   */
  async promote(
    key: string,
    options?: { reason?: string }
  ): Promise<{ promoted: boolean; key: string; old_tier: string; new_tier: string }> {
    const body: Record<string, unknown> = {};
    if (options?.reason) body.reason = options.reason;
    return this.client.request('POST', `/api/v1/memory/${encodeURIComponent(key)}/promote`, { body });
  }

  /**
   * Promote a continuum memory entry to a target tier.
   *
   * Matches the server contract for POST /api/v1/memory/{id}/promote
   * (`{ target_tier }` -> `{ success, previous_tier }`).
   *
   * A missing entry is HTTP 200 with `{ success: false, previous_tier: null,
   * error: 'Memory entry not found' }`, not a 404.
   *
   * @param memoryId - ID of the entry to promote (as returned by the store endpoint)
   * @param targetTier - Tier to promote the entry to
   *
   * @example
   * ```typescript
   * const result = await client.memory.promoteEntry('mem-123', 'slow');
   * if (result.success) {
   *   console.log(`Promoted from tier: ${result.previous_tier}`);
   * }
   * ```
   */
  async promoteEntry(
    memoryId: string,
    targetTier: MemoryTierType
  ): Promise<{ success: boolean; previous_tier: string | null; error?: string }> {
    return this.client.request('POST', `/api/v1/memory/${encodeURIComponent(memoryId)}/promote`, {
      body: { target_tier: targetTier },
    });
  }

  /**
   * Demote an entry to a slower tier.
   *
   * @deprecated POST /api/v1/memory/{key}/demote is declared in the handler's
   * ROUTES list but never dispatched, so this method always rejects with an
   * HTTP 500 (`handler_no_result`). The server has no demote endpoint —
   * demotion happens automatically during consolidation and cleanup.
   *
   * @param key - The entry key
   * @param options - Demotion options
   */
  async demote(
    key: string,
    options?: { reason?: string }
  ): Promise<{ demoted: boolean; key: string; old_tier: string; new_tier: string }> {
    const body: Record<string, unknown> = {};
    if (options?.reason) body.reason = options.reason;
    return this.client.request('POST', `/api/v1/memory/${encodeURIComponent(key)}/demote`, { body });
  }

  // ===========================================================================
  // Context Management (Extended)
  // ===========================================================================

  /**
   * Clear the memory context.
   *
   * Matches Python SDK's `clear_context()` method.
   *
   * @deprecated DELETE /api/v1/memory/context is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). The server has no
   * memory-context store; there is no replacement endpoint.
   *
   * @param contextId - Context ID to clear (current session if not specified)
   *
   * @example
   * ```typescript
   * await client.memory.clearContext('session-123');
   * ```
   */
  async clearContext(contextId?: string): Promise<{ cleared: boolean; context_id?: string }> {
    const params: Record<string, unknown> = {};
    if (contextId) params.context_id = contextId;
    return this.client.request('DELETE', '/api/v1/memory/context', { params });
  }

  // ===========================================================================
  // Analytics
  // ===========================================================================

  /**
   * Get memory analytics over time.
   *
   * @deprecated The analytics handler serves POST only for
   * /api/v1/memory/analytics/snapshot; this POST falls through to the GET
   * handler and returns HTTP 200 with *per-tier* analytics — not the
   * time-series shape declared here, which the server never produces. The
   * only parameter the server reads is a `days` window (1-365); everything
   * this method sends is ignored. Use {@link getTierAnalytics} instead.
   *
   * @param options - Analytics options
   */
  async getAnalytics(options?: {
    start_time?: string;
    end_time?: string;
    granularity?: 'minute' | 'hour' | 'day';
  }): Promise<MemoryAnalyticsResponse> {
    const params: Record<string, unknown> = {
      granularity: options?.granularity ?? 'hour',
    };
    if (options?.start_time) params.start_time = options.start_time;
    if (options?.end_time) params.end_time = options.end_time;
    return this.client.request('POST', '/api/v1/memory/analytics', { params });
  }

  /**
   * Get per-tier memory analytics.
   *
   * Matches the server contract for GET /api/v1/memory/analytics: tier stats,
   * promotion effectiveness, learning velocity, and recommendations over the
   * requested window.
   *
   * @param options - `days` is the analysis window (1-365, server default 30)
   *
   * @example
   * ```typescript
   * const analytics = await client.memory.getTierAnalytics({ days: 7 });
   * console.log(`Promotion effectiveness: ${analytics.promotion_effectiveness}`);
   * ```
   */
  async getTierAnalytics(options?: { days?: number }): Promise<TierAnalyticsResponse> {
    const params: Record<string, unknown> = {};
    if (options?.days !== undefined) params.days = options.days;
    return this.client.request('GET', '/api/v1/memory/analytics', { params });
  }

  // ===========================================================================
  // Additional Maintenance Operations
  // ===========================================================================

  /**
   * Run vacuum operation to reclaim storage space.
   *
   * Matches Python SDK's `vacuum()` method.
   *
   * @deprecated POST /api/v1/memory/vacuum is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). Use
   * {@link consolidate} for the supported maintenance operation.
   *
   * @example
   * ```typescript
   * const result = await client.memory.vacuum();
   * console.log(`Reclaimed ${result.space_reclaimed_bytes} bytes`);
   * ```
   */
  async vacuum(): Promise<VacuumResult> {
    return this.client.request('POST', '/api/v1/memory/vacuum', { body: {} });
  }

  /**
   * Rebuild memory search indices.
   *
   * Matches Python SDK's `rebuild_index()` method.
   *
   * @deprecated POST /api/v1/memory/rebuild-index is declared in the memory
   * handler's ROUTES list but never dispatched, so this method always fails
   * against a live server (HTTP 500 handler_no_result). There is no
   * replacement endpoint.
   *
   * @param options - Rebuild options
   *
   * @example
   * ```typescript
   * const result = await client.memory.rebuildIndex({ tier: 'slow' });
   * if (result.rebuilt) {
   *   console.log(`Rebuilt ${result.indexes_rebuilt} indexes`);
   * }
   * ```
   */
  async rebuildIndex(options?: {
    tier?: MemoryTierType;
  }): Promise<RebuildIndexResult> {
    const body: Record<string, unknown> = {};
    if (options?.tier) body.tier = options.tier;
    return this.client.request('POST', '/api/v1/memory/rebuild-index', { body });
  }

  // ===========================================================================
  // Critique Operations (Extended)
  // ===========================================================================

  /**
   * Store a critique in memory.
   *
   * @deprecated The server has no store-critique endpoint. This method sends
   * a GET with a request body, which fetch rejects outright, so the call never
   * reaches the server. (Even a raw POST to /api/v1/memory/critiques would be
   * a silent no-op: the dispatcher falls through to the GET handler and
   * returns 200 with the critique *listing*, storing nothing.) Critiques are
   * recorded server-side during debates; there is no client-facing write API.
   *
   * @param critique - The critique content
   * @param agent - Agent that generated the critique
   * @param options - Storage options
   */
  async storeCritique(
    critique: string,
    agent: string,
    options?: {
      debate_id?: string;
      target_agent?: string;
      score?: number;
      metadata?: Record<string, unknown>;
    }
  ): Promise<{ id: string; stored: boolean }> {
    const body: Record<string, unknown> = {
      critique,
      agent,
    };
    if (options?.debate_id) body.debate_id = options.debate_id;
    if (options?.target_agent) body.target_agent = options.target_agent;
    if (options?.score !== undefined) body.score = options.score;
    if (options?.metadata) body.metadata = options.metadata;
    return this.client.request('GET', '/api/v1/memory/critiques', { body });
  }

  /**
   * List memory entries.
   */
  async listEntries(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/memory/entries', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Get memory search index.
   */
  async searchIndex(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/memory/search-index', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Search memory timeline.
   */
  async searchTimeline(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/memory/search-timeline', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Get memory viewer.
   */
  async getViewer(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/memory/viewer', { params }) as Promise<Record<string, unknown>>;
  }
}
