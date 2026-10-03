/**
 * Batch Operations Namespace API
 *
 * Provides batch processing capabilities for debates, allowing multiple
 * debates to be queued and processed with status tracking.
 */

/**
 * Batch item status.
 */
export type BatchItemStatus = 'pending' | 'processing' | 'completed' | 'failed';

/**
 * Overall batch status.
 */
export type BatchStatus = 'pending' | 'processing' | 'completed' | 'partial_failure' | 'failed';

/**
 * A single item in a batch request.
 */
export interface BatchItem {
  question: string;
  agents?: string;
  rounds?: number;
  consensus?: string;
  priority?: number;
  metadata?: Record<string, unknown>;
}

/**
 * Batch submission request.
 */
export interface BatchSubmitRequest {
  items: BatchItem[];
  webhook_url?: string;
  webhook_headers?: Record<string, string>;
  max_parallel?: number;
}

/**
 * Batch submission response.
 */
export interface BatchSubmitResponse {
  success: boolean;
  batch_id: string;
  items_queued: number;
  status_url: string;
}

/**
 * Status of an individual batch item.
 */
export interface BatchItemResult {
  index: number;
  question: string;
  status: BatchItemStatus;
  debate_id?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

/**
 * Full batch status response.
 */
export interface BatchStatusResponse {
  batch_id: string;
  status: BatchStatus;
  total_items: number;
  completed_items: number;
  failed_items: number;
  pending_items: number;
  items: BatchItemResult[];
  created_at: string;
  updated_at: string;
  webhook_url?: string;
}

/**
 * Batch summary for listing.
 */
export interface BatchSummary {
  batch_id: string;
  status: BatchStatus;
  total_items: number;
  completed_items: number;
  failed_items: number;
  created_at: string;
}

/**
 * Queue status response.
 */
export interface QueueStatus {
  active: boolean;
  max_concurrent: number;
  active_count: number;
  total_batches: number;
  status_counts: Record<string, number>;
  message?: string;
}

/**
 * Options for listing batches.
 */
export interface ListBatchesOptions {
  limit?: number;
  status?: BatchStatus;
}

/**
 * Interface for the internal client methods used by BatchAPI.
 */
interface BatchClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Batch Operations API namespace.
 *
 * Provides batch processing capabilities for debates.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Submit a batch of debates
 * const response = await client.batch.submit({
 *   items: [
 *     { question: 'Should we use microservices?', rounds: 3 },
 *     { question: 'Is GraphQL better than REST?', rounds: 3 },
 *     { question: 'Should we migrate to TypeScript?', rounds: 3 }
 *   ],
 *   webhook_url: 'https://example.com/webhook',
 *   max_parallel: 2
 * });
 * console.log(`Batch ${response.batch_id} submitted`);
 *
 * // List all batches
 * const batches = await client.batch.list({ limit: 10 });
 * for (const batch of batches.batches) {
 *   console.log(`${batch.batch_id}: ${batch.status}`);
 * }
 *
 * // Get queue health
 * const queue = await client.batch.getQueueStatus();
 * console.log(`${queue.active_count} debates processing`);
 * ```
 */
export class BatchAPI {
  constructor(private client: BatchClientInterface) {}

  /**
   * Submit a batch of debates for processing.
   */
  async submit(request: BatchSubmitRequest): Promise<BatchSubmitResponse> {
    return this.client.request('POST', '/api/v1/batch', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * List batch requests.
   */
  async list(options?: ListBatchesOptions): Promise<{ batches: BatchSummary[]; count: number }> {
    return this.client.request('GET', '/api/v1/batch', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Get overall queue status.
   */
  async getQueueStatus(): Promise<QueueStatus> {
    return this.client.request('GET', '/api/v1/batch/queue/status');
  }
}
