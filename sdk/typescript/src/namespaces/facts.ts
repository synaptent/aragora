/**
 * Facts Namespace API
 *
 * Provides CRUD operations for knowledge facts and relationships.
 * Facts represent discrete pieces of knowledge with metadata, confidence scores,
 * and relationships to other facts in the knowledge graph.
 */

// =============================================================================
// Fact Types
// =============================================================================

/**
 * A fact represents a discrete piece of knowledge stored in the system.
 */
export interface Fact {
  /** Unique identifier for the fact */
  id: string;
  /** The content/text of the fact */
  content: string;
  /** The source from which this fact was derived */
  source: string;
  /** Confidence score between 0 and 1 */
  confidence: number;
  /** Optional metadata attached to the fact */
  metadata?: Record<string, unknown>;
  /** ISO timestamp of when the fact was created */
  created_at: string;
  /** ISO timestamp of when the fact was last updated */
  updated_at: string;
}

/**
 * A relationship between two facts in the knowledge graph.
 */
export interface Relationship {
  /** Unique identifier for the relationship */
  id: string;
  /** ID of the source fact */
  source_fact_id: string;
  /** ID of the target fact */
  target_fact_id: string;
  /** Type of relationship (e.g., 'supports', 'contradicts', 'related_to') */
  relationship_type: RelationshipType;
  /** Weight/strength of the relationship (0 to 1) */
  weight: number;
  /** Optional metadata for the relationship */
  metadata?: Record<string, unknown>;
  /** ISO timestamp of when the relationship was created */
  created_at: string;
}

/**
 * Valid relationship types between facts.
 */
export type RelationshipType =
  | 'supports'
  | 'contradicts'
  | 'elaborates'
  | 'derived_from'
  | 'related_to'
  | 'precedes'
  | 'follows'
  | 'causes'
  | 'caused_by';

// =============================================================================
// Request/Response Types
// =============================================================================

/**
 * Request to create a new fact.
 */
export interface CreateFactRequest {
  /** The content/text of the fact */
  content: string;
  /** The source from which this fact was derived */
  source: string;
  /** Confidence score between 0 and 1 (default: 1.0) */
  confidence?: number;
  /** Optional metadata to attach to the fact */
  metadata?: Record<string, unknown>;
  /** Optional tags for categorization */
  tags?: string[];
}

/**
 * Request to update an existing fact.
 */
export interface UpdateFactRequest {
  /** Updated content (optional) */
  content?: string;
  /** Updated source (optional) */
  source?: string;
  /** Updated confidence score (optional) */
  confidence?: number;
  /** Updated metadata (optional, replaces existing) */
  metadata?: Record<string, unknown>;
  /** Updated tags (optional) */
  tags?: string[];
}

/**
 * Options for listing facts.
 */
export interface ListFactsOptions {
  /** Pagination offset */
  offset?: number;
  /** Pagination limit */
  limit?: number;
  /** Filter by source */
  source?: string;
  /** Filter by tags (facts must have all specified tags) */
  tags?: string[];
  /** Filter by minimum confidence score */
  min_confidence?: number;
  /** Filter by maximum confidence score */
  max_confidence?: number;
  /** Sort field */
  sort_by?: 'created_at' | 'updated_at' | 'confidence';
  /** Sort direction */
  sort_order?: 'asc' | 'desc';
  /** Filter by creation date (ISO timestamp, facts created after this date) */
  created_after?: string;
  /** Filter by creation date (ISO timestamp, facts created before this date) */
  created_before?: string;
}

/**
 * Paginated response for listing facts.
 */
export interface PaginatedFacts {
  /** Array of facts */
  facts: Fact[];
  /** Total number of facts matching the query */
  total: number;
  /** Current offset */
  offset: number;
  /** Current limit */
  limit: number;
  /** Whether there are more results */
  has_more: boolean;
}

/**
 * Options for searching facts.
 */
export interface SearchOptions {
  /** Maximum number of results to return */
  limit?: number;
  /** Minimum relevance score (0 to 1) */
  min_relevance?: number;
  /** Filter by source */
  source?: string;
  /** Filter by tags */
  tags?: string[];
  /** Include relationship information in results */
  include_relationships?: boolean;
  /** Semantic search vs keyword search */
  semantic?: boolean;
}

/**
 * A fact with search relevance score.
 */
export interface SearchedFact extends Fact {
  /** Relevance score for the search (0 to 1) */
  relevance: number;
  /** Highlighted snippets from the content */
  highlights?: string[];
}

/**
 * Request to create a relationship between facts.
 */
export interface CreateRelationshipRequest {
  /** ID of the source fact */
  source_fact_id: string;
  /** ID of the target fact */
  target_fact_id: string;
  /** Type of relationship */
  relationship_type: RelationshipType;
  /** Weight/strength of the relationship (0 to 1, default: 1.0) */
  weight?: number;
  /** Optional metadata for the relationship */
  metadata?: Record<string, unknown>;
}

/**
 * Request to update a relationship.
 */
export interface UpdateRelationshipRequest {
  /** Updated relationship type (optional) */
  relationship_type?: RelationshipType;
  /** Updated weight (optional) */
  weight?: number;
  /** Updated metadata (optional) */
  metadata?: Record<string, unknown>;
}

/**
 * Options for getting relationships.
 */
export interface GetRelationshipsOptions {
  /** Filter by relationship type */
  relationship_type?: RelationshipType;
  /** Include both incoming and outgoing relationships */
  direction?: 'incoming' | 'outgoing' | 'both';
  /** Minimum weight threshold */
  min_weight?: number;
}

/**
 * Response for batch create operation.
 */
export interface BatchCreateResponse {
  /** Successfully created facts */
  created: Fact[];
  /** Failed creation attempts */
  failed: Array<{
    index: number;
    error: string;
    request: CreateFactRequest;
  }>;
  /** Total created */
  total_created: number;
  /** Total failed */
  total_failed: number;
}

/**
 * Response for batch delete operation.
 */
export interface BatchDeleteResponse {
  /** IDs that were successfully deleted */
  deleted: string[];
  /** IDs that failed to delete */
  failed: Array<{
    id: string;
    error: string;
  }>;
  /** Total deleted */
  total_deleted: number;
  /** Total failed */
  total_failed: number;
}

/**
 * Fact statistics.
 */
export interface FactStats {
  /** Total number of facts */
  total_facts: number;
  /** Total number of relationships */
  total_relationships: number;
  /** Facts grouped by source */
  by_source: Record<string, number>;
  /** Average confidence score */
  average_confidence: number;
  /** Facts created in the last 24 hours */
  created_last_24h: number;
  /** Facts updated in the last 24 hours */
  updated_last_24h: number;
}

// =============================================================================
// Client Interface
// =============================================================================

/**
 * Interface for the internal client methods used by FactsAPI.
 */
interface FactsClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: unknown }
  ): Promise<T>;
}

// =============================================================================
// Facts API Class
// =============================================================================

/**
 * Facts API namespace.
 *
 * Provides CRUD operations for knowledge facts and relationships:
 * - Creating, reading, updating, and deleting facts
 * - Searching facts with semantic and keyword search
 * - Managing relationships between facts
 * - Batch operations for bulk data management
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Create a fact
 * const fact = await client.facts.createFact({
 *   content: 'TypeScript was developed by Microsoft',
 *   source: 'official-docs',
 *   confidence: 0.95,
 * });
 *
 * // Search facts
 * const results = await client.facts.searchFacts('TypeScript features', {
 *   semantic: true,
 *   limit: 10,
 * });
 *
 * // Create a relationship
 * const rel = await client.facts.createRelationship({
 *   source_fact_id: fact.id,
 *   target_fact_id: 'other-fact-id',
 *   relationship_type: 'elaborates',
 *   weight: 0.8,
 * });
 *
 * // Get facts with pagination
 * const { facts, total } = await client.facts.listFacts({
 *   limit: 20,
 *   sort_by: 'created_at',
 *   sort_order: 'desc',
 * });
 * ```
 */
export class FactsAPI {
  constructor(private client: FactsClientInterface) {}

  // ===========================================================================
  // Fact CRUD Operations
  // ===========================================================================

  /**
   * Create a new fact.
   *
   * @param fact - The fact to create
   * @returns The created fact with generated ID and timestamps
   *
   * @example
   * ```typescript
   * const fact = await client.facts.createFact({
   *   content: 'The Earth orbits the Sun',
   *   source: 'astronomy-textbook',
   *   confidence: 0.99,
   *   metadata: { chapter: 1 },
   * });
   * console.log(`Created fact ${fact.id}`);
   * ```
   */
  async createFact(fact: CreateFactRequest): Promise<Fact> {
    return this.client.request('POST', '/api/v1/facts', { json: fact });
  }

  /**
   * Update an existing fact.
   *
   * @param id - The fact ID to update
   * @param updates - The fields to update
   * @returns The updated fact
   *
   * @example
   * ```typescript
   * const updated = await client.facts.updateFact('fact-123', {
   *   confidence: 0.85,
   *   metadata: { verified: true },
   * });
   * ```
   */
  async updateFact(id: string, updates: UpdateFactRequest): Promise<Fact> {
    return this.client.request('PATCH', `/api/v1/facts/${id}`, { json: updates });
  }

  /**
   * Delete a fact by ID.
   *
   * @param id - The fact ID to delete
   *
   * @example
   * ```typescript
   * await client.facts.deleteFact('fact-123');
   * console.log('Fact deleted');
   * ```
   */
  async deleteFact(id: string): Promise<void> {
    await this.client.request('DELETE', `/api/v1/facts/${id}`);
  }

  /**
   * Get a fact by ID.
   *
   * @param id - The fact ID to retrieve
   * @returns The fact
   *
   * @example
   * ```typescript
   * const fact = await client.facts.getFact('fact-123');
   * console.log(`Fact: ${fact.content}`);
   * ```
   */
  async getFact(id: string): Promise<Fact> {
    return this.client.request('GET', `/api/v1/facts/${id}`);
  }

  /**
   * List facts with pagination and filtering.
   *
   * @param options - Pagination and filter options
   * @returns Paginated list of facts
   *
   * @example
   * ```typescript
   * // Get recent high-confidence facts
   * const { facts, total } = await client.facts.listFacts({
   *   limit: 20,
   *   min_confidence: 0.9,
   *   sort_by: 'created_at',
   *   sort_order: 'desc',
   * });
   * console.log(`Found ${total} facts`);
   * ```
   */
  async listFacts(options?: ListFactsOptions): Promise<PaginatedFacts> {
    return this.client.request('GET', '/api/v1/facts', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Search facts using semantic or keyword search.
   *
   * @param query - The search query
   * @param options - Search options
   * @returns Array of facts with relevance scores
   *
   * @example
   * ```typescript
   * // Semantic search for related facts
   * const results = await client.facts.searchFacts('machine learning algorithms', {
   *   semantic: true,
   *   limit: 10,
   *   min_relevance: 0.5,
   * });
   * for (const fact of results) {
   *   console.log(`${fact.relevance.toFixed(2)}: ${fact.content}`);
   * }
   * ```
   */
  async searchFacts(query: string, options?: SearchOptions): Promise<SearchedFact[]> {
    const response = await this.client.request<{ results: SearchedFact[] }>(
      'GET',
      '/api/v1/facts/search',
      { params: { query, ...options } as Record<string, unknown> }
    );
    return response.results;
  }

  // ===========================================================================
  // Relationship Operations
  // ===========================================================================

  /**
   * Create a relationship between two facts.
   *
   * @param rel - The relationship to create
   * @returns The created relationship
   *
   * @example
   * ```typescript
   * const rel = await client.facts.createRelationship({
   *   source_fact_id: 'fact-1',
   *   target_fact_id: 'fact-2',
   *   relationship_type: 'supports',
   *   weight: 0.9,
   * });
   * console.log(`Created relationship ${rel.id}`);
   * ```
   */
  async createRelationship(rel: CreateRelationshipRequest): Promise<Relationship> {
    return this.client.request('POST', '/api/v1/facts/relationships', { json: rel });
  }

  /**
   * Get relationships for a fact.
   *
   * @param factId - The fact ID to get relationships for
   * @param options - Filter options
   * @returns Array of relationships
   *
   * @example
   * ```typescript
   * // Get all supporting relationships
   * const rels = await client.facts.getRelationships('fact-123', {
   *   relationship_type: 'supports',
   *   direction: 'outgoing',
   * });
   * console.log(`Found ${rels.length} supporting relationships`);
   * ```
   */
  async getRelationships(factId: string, options?: GetRelationshipsOptions): Promise<Relationship[]> {
    const response = await this.client.request<{ relationships: Relationship[] }>(
      'GET',
      `/api/v1/facts/${factId}/relationships`,
      { params: options as Record<string, unknown> }
    );
    return response.relationships;
  }

  /**
   * Update a relationship.
   *
   * @param id - The relationship ID to update
   * @param updates - The fields to update
   * @returns The updated relationship
   *
   * @example
   * ```typescript
   * const updated = await client.facts.updateRelationship('rel-123', {
   *   weight: 0.7,
   * });
   * ```
   */
  async updateRelationship(id: string, updates: UpdateRelationshipRequest): Promise<Relationship> {
    return this.client.request('PATCH', `/api/v1/facts/relationships/${id}`, { json: updates });
  }

  /**
   * Delete a relationship by ID.
   *
   * @param id - The relationship ID to delete
   *
   * @example
   * ```typescript
   * await client.facts.deleteRelationship('rel-123');
   * ```
   */
  async deleteRelationship(id: string): Promise<void> {
    await this.client.request('DELETE', `/api/v1/facts/relationships/${id}`);
  }

  /**
   * Get a specific relationship by ID.
   *
   * @param id - The relationship ID
   * @returns The relationship
   */
  async getRelationship(id: string): Promise<Relationship> {
    return this.client.request('GET', `/api/v1/facts/relationships/${id}`);
  }

  // ===========================================================================
  // Batch Operations
  // ===========================================================================

  /**
   * Create multiple facts in a single request.
   *
   * @param facts - Array of facts to create
   * @returns Batch creation result with created facts and any failures
   *
   * @example
   * ```typescript
   * const result = await client.facts.batchCreateFacts([
   *   { content: 'Fact 1', source: 'source-1', confidence: 0.9 },
   *   { content: 'Fact 2', source: 'source-2', confidence: 0.8 },
   * ]);
   * console.log(`Created ${result.total_created} facts`);
   * if (result.total_failed > 0) {
   *   console.log('Failures:', result.failed);
   * }
   * ```
   */
  async batchCreateFacts(facts: CreateFactRequest[]): Promise<BatchCreateResponse> {
    return this.client.request('POST', '/api/v1/facts/batch', { json: { facts } });
  }

  /**
   * Delete multiple facts in a single request.
   *
   * @param ids - Array of fact IDs to delete
   * @returns Batch deletion result
   *
   * @example
   * ```typescript
   * const result = await client.facts.batchDeleteFacts([
   *   'fact-1', 'fact-2', 'fact-3',
   * ]);
   * console.log(`Deleted ${result.total_deleted} facts`);
   * ```
   */
  async batchDeleteFacts(ids: string[]): Promise<BatchDeleteResponse> {
    return this.client.request('POST', '/api/v1/facts/batch/delete', { json: { ids } });
  }

  // ===========================================================================
  // Statistics & Utilities
  // ===========================================================================

  /**
   * Get statistics about the facts in the system.
   *
   * @returns Fact statistics
   *
   * @example
   * ```typescript
   * const stats = await client.facts.getStats();
   * console.log(`Total facts: ${stats.total_facts}`);
   * console.log(`Total relationships: ${stats.total_relationships}`);
   * console.log(`Average confidence: ${stats.average_confidence.toFixed(2)}`);
   * ```
   */
  async getStats(): Promise<FactStats> {
    return this.client.request('GET', '/api/v1/facts/stats');
  }

  /**
   * Verify if a fact exists by ID.
   *
   * @param id - The fact ID to check
   * @returns True if the fact exists, false otherwise
   *
   * @example
   * ```typescript
   * const exists = await client.facts.exists('fact-123');
   * if (!exists) {
   *   console.log('Fact not found');
   * }
   * ```
   */
  async exists(id: string): Promise<boolean> {
    try {
      const response = await this.client.request<{ exists: boolean }>(
        'HEAD',
        `/api/v1/facts/${id}`
      );
      return response?.exists ?? true;
    } catch {
      return false;
    }
  }

  /**
   * Get facts that are related to a given fact.
   *
   * @param factId - The fact ID to find related facts for
   * @param options - Options for filtering results
   * @returns Array of related facts with their relationships
   *
   * @example
   * ```typescript
   * const related = await client.facts.getRelatedFacts('fact-123', {
   *   relationship_type: 'supports',
   *   limit: 10,
   * });
   * for (const item of related) {
   *   console.log(`${item.relationship.relationship_type}: ${item.fact.content}`);
   * }
   * ```
   */
  async getRelatedFacts(
    factId: string,
    options?: GetRelationshipsOptions & { limit?: number }
  ): Promise<Array<{ fact: Fact; relationship: Relationship }>> {
    const response = await this.client.request<{ related: Array<{ fact: Fact; relationship: Relationship }> }>(
      'GET',
      `/api/v1/facts/${factId}/related`,
      { params: options as Record<string, unknown> }
    );
    return response.related;
  }

  /**
   * Validate fact content before creating.
   *
   * @param content - The content to validate
   * @returns Validation result with any issues
   *
   * @example
   * ```typescript
   * const validation = await client.facts.validateContent('Some fact content');
   * if (!validation.valid) {
   *   console.log('Issues:', validation.issues);
   * }
   * ```
   */
  async validateContent(content: string): Promise<{
    valid: boolean;
    issues: string[];
    suggestions?: string[];
  }> {
    return this.client.request('POST', '/api/v1/facts/validate', { json: { content } });
  }

  /**
   * Merge two facts into one.
   *
   * @param sourceId - The source fact ID (will be deleted)
   * @param targetId - The target fact ID (will be kept)
   * @param options - Merge options
   * @returns The merged fact
   *
   * @example
   * ```typescript
   * const merged = await client.facts.mergeFacts('fact-old', 'fact-main', {
   *   transfer_relationships: true,
   * });
   * console.log(`Merged into ${merged.id}`);
   * ```
   */
  async mergeFacts(
    sourceId: string,
    targetId: string,
    options?: { transfer_relationships?: boolean; merge_metadata?: boolean }
  ): Promise<Fact> {
    return this.client.request('POST', '/api/v1/facts/merge', {
      json: { source_id: sourceId, target_id: targetId, ...options },
    });
  }
}
