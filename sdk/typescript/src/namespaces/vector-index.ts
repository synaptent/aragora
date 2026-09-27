/**
 * Index Namespace API
 *
 * Provides vector index and semantic search operations.
 *
 * Features:
 * - Vector embedding generation
 * - Semantic similarity search
 * - Index management and operations
 * - Batch embedding processing
 */

// =============================================================================
// Types
// =============================================================================

/** Index status */
export type IndexStatus = 'ready' | 'building' | 'updating' | 'error';

/** Embedding request options */
export interface EmbedOptions {
  /** Single text to embed */
  text?: string;
  /** List of texts to embed (max 100) */
  texts?: string[];
  /** Optional model name to use for embedding */
  model?: string;
}

/** Batch embedding options */
export interface EmbedBatchOptions {
  /** List of texts to embed */
  texts: string[];
  /** Optional model name to use */
  model?: string;
  /** Number of texts per batch (max 100) */
  batch_size?: number;
}

/** Semantic search options */
export interface SearchOptions {
  /** Search query text */
  query: string;
  /** List of documents to search (max 1000) */
  documents: string[];
  /** Number of results to return (default 5) */
  top_k?: number;
  /** Minimum similarity score (0.0-1.0, default 0.0) */
  threshold?: number;
}

/** Named index search options */
export interface SearchIndexOptions {
  /** Search query text */
  query: string;
  /** Name of the index to search */
  index_name: string;
  /** Number of results to return */
  top_k?: number;
  /** Optional metadata filters */
  filters?: Record<string, unknown>;
}

/** Index creation options */
export interface CreateIndexOptions {
  /** Name for the new index */
  name: string;
  /** Vector dimension (auto-detected if not specified) */
  dimension?: number;
  /** Distance metric (cosine, euclidean, dot_product) */
  metric?: string;
  /** Optional description */
  description?: string;
}

// =============================================================================
// Index API
// =============================================================================

interface IndexClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Index namespace API for vector indexing and semantic search.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Generate embeddings
 * const result = await client.index.embed({ texts: ['hello world', 'machine learning'] });
 *
 * // Semantic search
 * const results = await client.index.search({
 *   query: 'AI safety',
 *   documents: ['neural networks', 'safety constraints', 'ethics'],
 * });
 * ```
 */
export class IndexAPI {
  constructor(private client: IndexClientInterface) {}

  // ===========================================================================
  // Embedding Operations
  // ===========================================================================

  /**
   * Generate vector embeddings for text.
   *
   * Provide either a single text or a list of texts (max 100).
   */
  async embed(options: EmbedOptions): Promise<{ embeddings: number[][]; dimension: number }> {
    const data: Record<string, unknown> = {};
    if (options.text !== undefined) data.text = options.text;
    if (options.texts !== undefined) data.texts = options.texts;
    if (options.model !== undefined) data.model = options.model;
    return this.client.request('POST', '/api/v1/ml/embed', { json: data });
  }

  /**
   * Generate embeddings for a large batch of texts.
   *
   * Automatically handles batching for large datasets.
   */
  async embedBatch(options: EmbedBatchOptions): Promise<{ embeddings: number[][]; dimension: number; batch_count: number }> {
    const data: Record<string, unknown> = {
      texts: options.texts,
      batch_size: Math.min(options.batch_size ?? 100, 100),
    };
    if (options.model !== undefined) data.model = options.model;
    return this.client.request('POST', '/api/v1/index/embed-batch', { json: data });
  }

  // ===========================================================================
  // Semantic Search
  // ===========================================================================

  /**
   * Perform semantic similarity search.
   */
  async search(options: SearchOptions): Promise<{ results: Array<{ text: string; score: number; index: number }> }> {
    return this.client.request('POST', '/api/v1/ml/search', {
      json: {
        query: options.query,
        documents: options.documents,
        top_k: options.top_k ?? 5,
        threshold: options.threshold ?? 0.0,
      },
    });
  }

  /**
   * Search a named vector index.
   */
  async searchIndex(options: SearchIndexOptions): Promise<{ results: Array<{ text: string; score: number; metadata?: Record<string, unknown> }> }> {
    const data: Record<string, unknown> = {
      query: options.query,
      index_name: options.index_name,
      top_k: options.top_k ?? 10,
    };
    if (options.filters !== undefined) data.filters = options.filters;
    return this.client.request('POST', '/api/v1/index/search', { json: data });
  }

  // ===========================================================================
  // Index Management
  // ===========================================================================

  /** List all available vector indexes. */
  async listIndexes(): Promise<{ indexes: Array<{ name: string; status: IndexStatus; document_count: number; dimension: number }> }> {
    return this.client.request('GET', '/api/v1/index');
  }

  /** Get details of a specific index. */
  async getIndex(indexName: string): Promise<{ name: string; status: IndexStatus; document_count: number; dimension: number }> {
    return this.client.request('GET', `/api/v1/index/${indexName}`);
  }

  /** Create a new vector index. */
  async createIndex(options: CreateIndexOptions): Promise<{ name: string; status: IndexStatus; created_at: string }> {
    const data: Record<string, unknown> = {
      name: options.name,
      metric: options.metric ?? 'cosine',
    };
    if (options.dimension !== undefined) data.dimension = options.dimension;
    if (options.description !== undefined) data.description = options.description;
    return this.client.request('POST', '/api/v1/index', { json: data });
  }

  /** Delete a vector index. */
  async deleteIndex(indexName: string): Promise<{ deleted: boolean }> {
    return this.client.request('DELETE', `/api/v1/index/${indexName}`);
  }
}
