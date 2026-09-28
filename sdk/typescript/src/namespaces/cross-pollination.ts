/**
 * Cross-Pollination Namespace API
 *
 * Provides a namespaced interface for cross-debate knowledge sharing
 * and Knowledge Mound integration. Enables insights and patterns from
 * one debate to inform and improve others.
 */

/**
 * Circuit breaker status
 */
export type CircuitBreakerStatus = 'closed' | 'open' | 'half_open';

/**
 * Cross-pollination statistics
 */
export interface CrossPollinationStats {
  total_events: number;
  successful_pollinations: number;
  failed_pollinations: number;
  circuit_breaker_status: CircuitBreakerStatus;
  last_event_at?: string;
  handlers_registered: number;
}

/**
 * Cross-pollination subscriber
 */
export interface CrossPollinationSubscriber {
  id: string;
  name: string;
  event_types: string[];
  active: boolean;
  created_at: string;
  last_triggered_at?: string;
  trigger_count: number;
}

/**
 * Subscription result
 */
export interface SubscriptionResult {
  success: boolean;
  debate_id: string;
  subscribed_topics?: string[];
  min_confidence?: number;
  message?: string;
}

/**
 * Cross-pollination bridge status
 */
export interface CrossPollinationBridge {
  source_debate_id: string;
  target_debate_id: string;
  bridge_type: string;
  status: 'active' | 'inactive' | 'failed';
  created_at: string;
  last_sync_at?: string;
  sync_count: number;
}

/**
 * Bridge configuration
 */
export interface BridgeConfiguration {
  enabled: boolean;
  max_pollinations_per_debate: number;
  confidence_threshold: number;
  updated_at?: string;
}

/**
 * Cross-pollination suggestion
 */
export interface CrossPollinationSuggestion {
  source_debate_id: string;
  source_topic?: string;
  relevance_score: number;
  insight: string;
  confidence: number;
  suggested_at: string;
}

/**
 * Cross-pollination metrics
 */
export interface CrossPollinationMetrics {
  events_per_minute: number;
  avg_latency_ms: number;
  success_rate: number;
  queue_depth: number;
  active_bridges: number;
}

/**
 * Knowledge Mound integration status
 */
export interface KMIntegrationStatus {
  adapters: Record<string, {
    status: string;
    last_sync_at?: string;
    items_synced: number;
  }>;
  batch_queue: {
    pending: number;
    processing: number;
    failed: number;
  };
  handlers: Record<string, {
    events_processed: number;
    last_event_at?: string;
  }>;
}

/**
 * KM sync result
 */
export interface KMSyncResult {
  adapters: Record<string, {
    success: boolean;
    items_synced: number;
    duration_ms: number;
    error?: string;
  }>;
  total_duration_ms: number;
}

/**
 * KM staleness check result
 */
export interface KMStalenessResult {
  stale_nodes: number;
  checked_nodes: number;
  revalidated_nodes: number;
  errors?: string[];
}

/**
 * Culture pattern
 */
export interface CulturePattern {
  pattern_type: string;
  confidence: number;
  occurrences: number;
  last_seen_at: string;
  metadata?: Record<string, unknown>;
}

/**
 * Workspace culture
 */
export interface WorkspaceCulture {
  workspace_id: string;
  debate_style_preferences: Record<string, number>;
  organizational_patterns: CulturePattern[];
  extracted_at: string;
}

/**
 * Interface for the internal client used by CrossPollinationAPI.
 */
interface CrossPollinationClientInterface {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  put<T>(path: string, body?: unknown): Promise<T>;
  delete<T>(path: string): Promise<T>;
  request<T>(method: string, path: string, options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }): Promise<T>;
}

/**
 * Cross-Pollination API namespace.
 *
 * Provides methods for cross-debate knowledge sharing:
 * - Monitor cross-pollination statistics and metrics
 * - Manage subscribers and bridges
 * - Knowledge Mound integration and sync
 * - Culture pattern extraction
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // Get cross-pollination stats
 * const stats = await client.crossPollination.getStats();
 * console.log(`Success rate: ${stats.successful_pollinations / stats.total_events}`);
 *
 * // Check KM integration status
 * const kmStatus = await client.crossPollination.getKMStatus();
 *
 * // Trigger manual KM sync
 * const syncResult = await client.crossPollination.syncKM();
 *
 * // Get culture patterns for a workspace
 * const culture = await client.crossPollination.getCulture('workspace-123');
 * ```
 */
export class CrossPollinationAPI {
  constructor(private client: CrossPollinationClientInterface) {}

  // ===========================================================================
  // Statistics & Monitoring
  // ===========================================================================

  /**
   * Get cross-pollination statistics.
   */
  async getStats(): Promise<CrossPollinationStats> {
    return this.client.get('/api/v1/cross-pollination/stats');
  }

  /**
   * Get cross-pollination metrics.
   */
  async getMetrics(): Promise<CrossPollinationMetrics> {
    return this.client.get('/api/v1/cross-pollination/metrics');
  }

  /**
   * Reset all cross-pollination statistics.
   * Useful for testing and debugging.
   */
  async resetStats(): Promise<{ reset: boolean; handlers_count: number }> {
    return this.client.post('/api/v1/cross-pollination/reset');
  }

  // ===========================================================================
  // Subscriber Management
  // ===========================================================================

  /**
   * List cross-pollination subscribers.
   *
   * @returns Object containing array of subscribers and total count
   *
   * @example
   * ```typescript
   * const { subscribers, total } = await client.crossPollination.getSubscribers();
   * console.log(`Total subscribers: ${total}`);
   * for (const sub of subscribers) {
   *   console.log(`${sub.name}: ${sub.active ? 'active' : 'inactive'}`);
   * }
   * ```
   */
  async getSubscribers(): Promise<{ subscribers: CrossPollinationSubscriber[]; total: number }> {
    return this.client.get('/api/v1/cross-pollination/subscribers');
  }

  /**
   * Subscribe a debate to cross-pollination.
   *
   * Subscribes a debate to receive cross-pollinated insights from other debates.
   * Optionally filter by specific topics or set a minimum confidence threshold.
   *
   * @param debateId - Debate ID to subscribe
   * @param options - Optional subscription configuration
   * @param options.topics - Topics to subscribe to (all if not specified)
   * @param options.minConfidence - Minimum confidence threshold (0-1)
   * @returns Subscription result
   *
   * @example
   * ```typescript
   * // Subscribe to all cross-pollinations
   * const result = await client.crossPollination.subscribe('debate-123');
   *
   * // Subscribe to specific topics with confidence threshold
   * const filtered = await client.crossPollination.subscribe('debate-123', {
   *   topics: ['machine-learning', 'ethics'],
   *   minConfidence: 0.8
   * });
   * ```
   */
  async subscribe(
    debateId: string,
    options?: {
      topics?: string[];
      minConfidence?: number;
    }
  ): Promise<SubscriptionResult> {
    const json: Record<string, unknown> = { debate_id: debateId };
    if (options?.topics) {
      json.topics = options.topics;
    }
    if (options?.minConfidence !== undefined) {
      json.min_confidence = options.minConfidence;
    }
    return this.client.request('POST', '/api/v1/cross-pollination/subscribe', { json });
  }

  // ===========================================================================
  // Bridge Configuration
  // ===========================================================================

  /**
   * Get active cross-pollination bridges.
   *
   * @returns Object containing array of bridges and total count
   */
  async getBridges(): Promise<{ bridges: CrossPollinationBridge[]; total: number }> {
    return this.client.get('/api/v1/cross-pollination/bridge');
  }

  /**
   * Get current bridge configuration.
   *
   * @returns Current bridge configuration settings
   *
   * @example
   * ```typescript
   * const config = await client.crossPollination.getBridgeConfig();
   * console.log(`Bridge enabled: ${config.enabled}`);
   * console.log(`Confidence threshold: ${config.confidence_threshold}`);
   * ```
   */
  async getBridgeConfig(): Promise<BridgeConfiguration> {
    return this.client.get('/api/v1/cross-pollination/bridge');
  }

  /**
   * Configure the cross-pollination bridge.
   *
   * Updates bridge settings such as enabling/disabling, maximum pollinations,
   * and confidence thresholds.
   *
   * @param options - Bridge configuration options
   * @param options.enabled - Enable/disable the bridge
   * @param options.maxPollinationsPerDebate - Maximum pollinations per debate
   * @param options.confidenceThreshold - Confidence threshold for pollinations (0-1)
   * @returns Updated bridge configuration
   *
   * @example
   * ```typescript
   * // Enable bridge with custom thresholds
   * const config = await client.crossPollination.configureBridge({
   *   enabled: true,
   *   maxPollinationsPerDebate: 10,
   *   confidenceThreshold: 0.75
   * });
   *
   * // Disable bridge
   * await client.crossPollination.configureBridge({ enabled: false });
   * ```
   */
  async configureBridge(options: {
    enabled?: boolean;
    maxPollinationsPerDebate?: number;
    confidenceThreshold?: number;
  }): Promise<BridgeConfiguration> {
    const json: Record<string, unknown> = {};
    if (options.enabled !== undefined) {
      json.enabled = options.enabled;
    }
    if (options.maxPollinationsPerDebate !== undefined) {
      json.max_pollinations_per_debate = options.maxPollinationsPerDebate;
    }
    if (options.confidenceThreshold !== undefined) {
      json.confidence_threshold = options.confidenceThreshold;
    }
    return this.client.request('GET', '/api/v1/cross-pollination/bridge', { params: json });
  }

  // ===========================================================================
  // Knowledge Mound Integration
  // ===========================================================================

  /**
   * Get Knowledge Mound integration status.
   */
  async getKMStatus(): Promise<KMIntegrationStatus> {
    return this.client.get('/api/v1/cross-pollination/km');
  }

  /**
   * Trigger manual sync of KM adapters.
   * Useful for forcing persistence after important debates or before shutdown.
   */
  async syncKM(): Promise<KMSyncResult> {
    return this.client.post('/api/v1/cross-pollination/km/sync');
  }

  /**
   * Check for stale cross-pollinated knowledge.
   *
   * Identifies knowledge that may be outdated or needs revalidation.
   *
   * @returns Staleness report with counts and any errors
   *
   * @example
   * ```typescript
   * const staleness = await client.crossPollination.checkKMStaleness();
   * console.log(`Stale nodes: ${staleness.stale_nodes} / ${staleness.checked_nodes}`);
   * if (staleness.revalidated_nodes > 0) {
   *   console.log(`Revalidated: ${staleness.revalidated_nodes}`);
   * }
   * ```
   */
  async checkKMStaleness(): Promise<KMStalenessResult> {
    return this.client.get('/api/v1/cross-pollination/km/staleness-check');
  }

  /**
   * Get culture patterns for a workspace.
   *
   * Extracts organizational patterns and debate style preferences from
   * cross-pollinated knowledge.
   *
   * @param workspaceId - Workspace ID (default: 'default')
   * @returns Workspace culture patterns and preferences
   *
   * @example
   * ```typescript
   * const culture = await client.crossPollination.getCulture('workspace-123');
   * console.log(`Debate preferences:`, culture.debate_style_preferences);
   * for (const pattern of culture.organizational_patterns) {
   *   console.log(`${pattern.pattern_type}: ${pattern.confidence}`);
   * }
   * ```
   */
  async getCulture(workspaceId: string = 'default'): Promise<WorkspaceCulture> {
    return this.client.request('GET', '/api/v1/cross-pollination/km/culture', {
      params: { workspace_id: workspaceId },
    });
  }

  // ===========================================================================
  // Laboratory (Suggestions)
  // ===========================================================================

  /**
   * Get cross-pollination suggestions.
   *
   * Returns suggestions for cross-pollinating insights from other debates.
   * Can be filtered by debate ID, topic, or limited to a specific count.
   *
   * @param options - Suggestion filter options
   * @param options.debateId - Debate ID to get suggestions for
   * @param options.topic - Topic to get suggestions for
   * @param options.limit - Maximum suggestions to return (default: 10)
   * @returns Object containing array of suggestions
   *
   * @example
   * ```typescript
   * // Get suggestions for a specific debate
   * const { suggestions } = await client.crossPollination.suggest({
   *   debateId: 'debate-123',
   *   limit: 5
   * });
   *
   * // Get suggestions by topic
   * const topicSuggestions = await client.crossPollination.suggest({
   *   topic: 'machine-learning'
   * });
   *
   * for (const s of topicSuggestions.suggestions) {
   *   console.log(`From ${s.source_debate_id}: ${s.insight} (${s.relevance_score})`);
   * }
   * ```
   */
  async suggest(options?: {
    debateId?: string;
    topic?: string;
    limit?: number;
  }): Promise<{ suggestions: CrossPollinationSuggestion[] }> {
    const params: Record<string, unknown> = {
      limit: options?.limit ?? 10,
    };
    if (options?.debateId) {
      params.debate_id = options.debateId;
    }
    if (options?.topic) {
      params.topic = options.topic;
    }
    return this.client.request('GET', '/api/v1/laboratory/cross-pollinations/suggest', { params });
  }

  // ===========================================================================
  // Conflict Resolution
  // ===========================================================================

  /**
   * Get pending cross-pollination conflicts.
   *
   * Returns conflicts that have arisen from cross-pollinated knowledge
   * that may contradict existing knowledge.
   *
   * @param options - Filter options
   * @param options.debateId - Filter by debate ID
   * @param options.status - Filter by conflict status
   * @param options.limit - Maximum conflicts to return
   * @returns Object containing array of conflicts
   *
   * @example
   * ```typescript
   * const { conflicts } = await client.crossPollination.getConflicts({
   *   status: 'pending',
   *   limit: 20
   * });
   *
   * for (const conflict of conflicts) {
   *   console.log(`Conflict: ${conflict.description}`);
   *   console.log(`  Source: ${conflict.source_node_id}`);
   *   console.log(`  Target: ${conflict.target_node_id}`);
   * }
   * ```
   */
  async getConflicts(options?: {
    debateId?: string;
    status?: 'pending' | 'resolved' | 'dismissed';
    limit?: number;
  }): Promise<{
    conflicts: Array<{
      id: string;
      source_node_id: string;
      target_node_id: string;
      description: string;
      status: 'pending' | 'resolved' | 'dismissed';
      created_at: string;
      resolved_at?: string;
      resolution?: string;
    }>;
    total: number;
  }> {
    const params: Record<string, unknown> = {};
    if (options?.debateId) {
      params.debate_id = options.debateId;
    }
    if (options?.status) {
      params.status = options.status;
    }
    if (options?.limit) {
      params.limit = options.limit;
    }
    return this.client.request('GET', '/api/v1/cross-pollination/conflicts', { params });
  }

  // ===========================================================================
  // Federation Operations
  // ===========================================================================

  /**
   * Get federation status.
   *
   * Returns the status of cross-pollination federation with external systems.
   *
   * @returns Federation status and connected peers
   *
   * @example
   * ```typescript
   * const federation = await client.crossPollination.getFederationStatus();
   * console.log(`Federation enabled: ${federation.enabled}`);
   * console.log(`Connected peers: ${federation.peers.length}`);
   * ```
   */
  async getFederationStatus(): Promise<{
    enabled: boolean;
    peers: Array<{
      id: string;
      name: string;
      url: string;
      status: 'connected' | 'disconnected' | 'error';
      last_sync_at?: string;
      items_shared: number;
      items_received: number;
    }>;
    last_federation_at?: string;
  }> {
    return this.client.request('GET', '/api/v1/cross-pollination/federation');
  }

  /**
   * Trigger federation sync with external peers.
   *
   * @param options - Sync options
   * @param options.peerId - Specific peer to sync with (all if not specified)
   * @param options.direction - Sync direction
   * @returns Sync result
   *
   * @example
   * ```typescript
   * // Sync with all peers
   * const result = await client.crossPollination.syncFederation();
   *
   * // Sync with specific peer
   * const peerResult = await client.crossPollination.syncFederation({
   *   peerId: 'peer-123',
   *   direction: 'bidirectional'
   * });
   * ```
   */
  async syncFederation(options?: {
    peerId?: string;
    direction?: 'push' | 'pull' | 'bidirectional';
  }): Promise<{
    success: boolean;
    peers_synced: number;
    items_pushed: number;
    items_pulled: number;
    duration_ms: number;
    errors?: string[];
  }> {
    const json: Record<string, unknown> = {};
    if (options?.peerId) {
      json.peer_id = options.peerId;
    }
    if (options?.direction) {
      json.direction = options.direction;
    }
    return this.client.request('POST', '/api/v1/cross-pollination/federation/sync', { json });
  }

  // ===========================================================================
  // Sync Status
  // ===========================================================================

  /**
   * Get cross-pollination sync status.
   *
   * Returns the current status of cross-pollination synchronization,
   * including pending items and recent sync history.
   *
   * @returns Sync status information
   *
   * @example
   * ```typescript
   * const status = await client.crossPollination.getSyncStatus();
   * console.log(`Pending: ${status.pending_items}`);
   * console.log(`Last sync: ${status.last_sync_at}`);
   * if (status.errors.length > 0) {
   *   console.error('Sync errors:', status.errors);
   * }
   * ```
   */
  async getSyncStatus(): Promise<{
    pending_items: number;
    processing_items: number;
    failed_items: number;
    last_sync_at?: string;
    next_sync_at?: string;
    sync_interval_seconds: number;
    errors: string[];
    recent_syncs: Array<{
      timestamp: string;
      items_synced: number;
      duration_ms: number;
      success: boolean;
    }>;
  }> {
    return this.client.request('GET', '/api/v1/cross-pollination/sync/status');
  }

  /**
   * Trigger manual cross-pollination sync.
   *
   * Forces an immediate synchronization of cross-pollinated knowledge.
   *
   * @returns Sync result
   *
   * @example
   * ```typescript
   * const result = await client.crossPollination.triggerSync();
   * console.log(`Synced ${result.items_synced} items in ${result.duration_ms}ms`);
   * ```
   */
  async triggerSync(): Promise<{
    success: boolean;
    items_synced: number;
    duration_ms: number;
    errors?: string[];
  }> {
    return this.client.request('POST', '/api/v1/cross-pollination/sync/trigger');
  }
}
