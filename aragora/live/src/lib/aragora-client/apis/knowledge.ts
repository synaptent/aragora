/**
 * Knowledge Mound API
 *
 * Handles knowledge mound operations including node CRUD, semantic search,
 * graph traversal, sharing, federation, and analytics.
 *
 * The Knowledge Mound is Aragora's unified knowledge management system with
 * 120+ endpoints across 20 operation categories.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface KnowledgeNode {
  id: string;
  content: string;
  type: string;
  confidence: number;
  domain?: string;
  source?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface CreateNodeRequest {
  content: string;
  type: string;
  confidence?: number;
  domain?: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

export interface NodeListParams {
  type?: string;
  domain?: string;
  min_confidence?: number;
  limit?: number;
  offset?: number;
}

export interface NodeListResponse {
  nodes: KnowledgeNode[];
  total: number;
}

export interface Relationship {
  id: string;
  source_id: string;
  target_id: string;
  type: string;
  weight?: number;
  metadata?: Record<string, unknown>;
}

export interface CreateRelationshipRequest {
  source_id: string;
  target_id: string;
  type: string;
  weight?: number;
  metadata?: Record<string, unknown>;
}

export interface QueryOptions {
  query: string;
  limit?: number;
  min_confidence?: number;
  domain?: string;
  types?: string[];
}

export interface QueryResult {
  node: KnowledgeNode;
  score: number;
  relationships?: Relationship[];
}

export interface QueryResponse {
  results: QueryResult[];
  total: number;
  query_time_ms: number;
}

export interface GraphTraversalOptions {
  depth?: number;
  limit?: number;
  relationship_types?: string[];
}

export interface GraphNode {
  id: string;
  content: string;
  type: string;
  confidence: number;
  depth: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: Relationship[];
  root_id: string;
}

export type VisibilityLevel = 'private' | 'workspace' | 'organization' | 'global';

export interface VisibilityInfo {
  node_id: string;
  level: VisibilityLevel;
  shared_with?: string[];
}

export interface AccessGrant {
  node_id: string;
  grantee_id: string;
  permission: 'read' | 'write' | 'admin';
  granted_at: string;
}

export interface ShareRequest {
  node_id: string;
  target_id: string;
  permission?: 'read' | 'write';
}

export interface ShareResult {
  success: boolean;
  share_id?: string;
}

export interface MoundStats {
  total_nodes: number;
  total_relationships: number;
  avg_confidence: number;
  domains: Record<string, number>;
  types: Record<string, number>;
  last_updated?: string;
}

export interface FederationRegion {
  id: string;
  name: string;
  endpoint: string;
  status: 'active' | 'inactive' | 'syncing';
  last_sync?: string;
}

export interface SyncResult {
  success: boolean;
  nodes_synced: number;
  conflicts: number;
  duration_ms: number;
}

export interface CultureProfile {
  values: Record<string, number>;
  patterns: string[];
  last_updated?: string;
}

export interface Checkpoint {
  name: string;
  created_at: string;
  node_count: number;
  size_bytes?: number;
  description?: string;
}

export interface CheckpointListResponse {
  checkpoints: Checkpoint[];
  total: number;
}

export interface ContradictionResult {
  id: string;
  node_a_id: string;
  node_b_id: string;
  description: string;
  severity: 'high' | 'medium' | 'low';
  status: 'unresolved' | 'resolved' | 'dismissed';
}

export interface AnalyticsSummary {
  mound_stats: MoundStats;
  sharing_stats: { shared_items: number; active_grants: number };
  federation_stats: { regions: number; total_syncs: number };
  learning_stats: { debates_processed: number; nodes_extracted: number };
}

// =============================================================================
// Knowledge Mound API Class
// =============================================================================

export class KnowledgeAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  // ===========================================================================
  // Node Operations
  // ===========================================================================

  /**
   * Create a knowledge node
   */
  async createNode(data: CreateNodeRequest): Promise<KnowledgeNode> {
    return this.http.post('/api/v1/knowledge/mound/nodes', data);
  }

  /**
   * List knowledge nodes with optional filtering
   */
  async listNodes(params?: NodeListParams): Promise<NodeListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.type) searchParams.set('type', params.type);
    if (params?.domain) searchParams.set('domain', params.domain);
    if (params?.min_confidence)
      searchParams.set('min_confidence', params.min_confidence.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.offset) searchParams.set('offset', params.offset.toString());

    const query = searchParams.toString();
    return this.http.get(`/api/v1/knowledge/mound/nodes${query ? `?${query}` : ''}`);
  }

  /**
   * Get a specific knowledge node by ID
   */
  async getNode(id: string): Promise<KnowledgeNode> {
    return this.http.get(`/api/v1/knowledge/mound/nodes/${id}`);
  }

  /**
   * Get relationships for a specific node
   */
  async getNodeRelationships(nodeId: string): Promise<Relationship[]> {
    return this.http.get(`/api/v1/knowledge/mound/nodes/${nodeId}/relationships`);
  }

  // ===========================================================================
  // Relationships
  // ===========================================================================

  /**
   * Create a relationship between two nodes
   */
  async createRelationship(data: CreateRelationshipRequest): Promise<Relationship> {
    return this.http.post('/api/v1/knowledge/mound/relationships', data);
  }

  // ===========================================================================
  // Semantic Search & Query
  // ===========================================================================

  /**
   * Semantic query against the knowledge mound
   */
  async query(options: QueryOptions): Promise<QueryResponse> {
    return this.http.post('/api/v1/knowledge/mound/query', options);
  }

  // ===========================================================================
  // Graph Traversal
  // ===========================================================================

  /**
   * Traverse the knowledge graph from a starting node
   */
  async traverseGraph(nodeId: string, options?: GraphTraversalOptions): Promise<GraphResponse> {
    const params = new URLSearchParams();
    if (options?.depth) params.set('depth', options.depth.toString());
    if (options?.limit) params.set('limit', options.limit.toString());
    if (options?.relationship_types) params.set('types', options.relationship_types.join(','));

    const query = params.toString();
    return this.http.get(`/api/v1/knowledge/mound/graph/${nodeId}${query ? `?${query}` : ''}`);
  }

  /**
   * Get the lineage/provenance chain for a node
   */
  async getLineage(nodeId: string): Promise<GraphResponse> {
    return this.http.get(`/api/v1/knowledge/mound/graph/${nodeId}/lineage`);
  }

  /**
   * Get related nodes
   */
  async getRelated(nodeId: string): Promise<GraphResponse> {
    return this.http.get(`/api/v1/knowledge/mound/graph/${nodeId}/related`);
  }

  /**
   * Export the knowledge graph as D3-compatible JSON
   */
  async exportD3(): Promise<unknown> {
    return this.http.get('/api/v1/knowledge/mound/export/d3');
  }

  // ===========================================================================
  // Visibility & Access Control
  // ===========================================================================

  /**
   * Get visibility settings for a node
   */
  async getVisibility(nodeId: string): Promise<VisibilityInfo> {
    return this.http.get(`/api/v1/knowledge/mound/nodes/${nodeId}/visibility`);
  }

  /**
   * Set visibility level for a node
   */
  async setVisibility(nodeId: string, level: VisibilityLevel): Promise<void> {
    return this.http.put(`/api/v1/knowledge/mound/nodes/${nodeId}/visibility`, { level });
  }

  /**
   * List access grants for a node
   */
  async listAccess(nodeId: string): Promise<AccessGrant[]> {
    return this.http.get(`/api/v1/knowledge/mound/nodes/${nodeId}/access`);
  }

  /**
   * Grant access to a node
   */
  async grantAccess(
    nodeId: string,
    granteeId: string,
    permission: 'read' | 'write' | 'admin',
  ): Promise<void> {
    return this.http.post(`/api/v1/knowledge/mound/nodes/${nodeId}/access`, {
      grantee_id: granteeId,
      permission,
    });
  }

  /**
   * Revoke access to a node
   */
  async revokeAccess(nodeId: string, granteeId: string): Promise<void> {
    return this.http.delete(`/api/v1/knowledge/mound/nodes/${nodeId}/access`, {
      grantee_id: granteeId,
    });
  }

  // ===========================================================================
  // Sharing
  // ===========================================================================

  /**
   * Share a knowledge item with a user or workspace
   */
  async share(request: ShareRequest): Promise<ShareResult> {
    return this.http.post('/api/v1/knowledge/mound/share', request);
  }

  /**
   * Get items shared with the current user
   */
  async sharedWithMe(): Promise<KnowledgeNode[]> {
    return this.http.get('/api/v1/knowledge/mound/shared-with-me');
  }

  /**
   * List items the current user has shared
   */
  async myShares(): Promise<KnowledgeNode[]> {
    return this.http.get('/api/v1/knowledge/mound/my-shares');
  }

  // ===========================================================================
  // Statistics & Dashboard
  // ===========================================================================

  /**
   * Get knowledge mound statistics
   */
  async stats(): Promise<MoundStats> {
    return this.http.get('/api/v1/knowledge/mound/stats');
  }

  /**
   * Get combined analytics summary
   */
  async analyticsSummary(): Promise<AnalyticsSummary> {
    return this.http.get('/api/v1/knowledge/analytics/summary');
  }

  /**
   * Get KM dashboard health status
   */
  async dashboardHealth(): Promise<unknown> {
    return this.http.get('/api/v1/knowledge/mound/dashboard/health');
  }

  /**
   * Get real-time dashboard metrics
   */
  async dashboardMetrics(): Promise<unknown> {
    return this.http.get('/api/v1/knowledge/mound/dashboard/metrics');
  }

  // ===========================================================================
  // Culture
  // ===========================================================================

  /**
   * Get the organizational culture profile
   */
  async getCulture(): Promise<CultureProfile> {
    return this.http.get('/api/v1/knowledge/mound/culture');
  }

  /**
   * Add a culture document
   */
  async addCultureDocument(content: string, metadata?: Record<string, unknown>): Promise<void> {
    return this.http.post('/api/v1/knowledge/mound/culture/documents', { content, metadata });
  }

  // ===========================================================================
  // Staleness & Revalidation
  // ===========================================================================

  /**
   * Get stale knowledge items that need revalidation
   */
  async getStaleItems(): Promise<KnowledgeNode[]> {
    return this.http.get('/api/v1/knowledge/mound/stale');
  }

  /**
   * Revalidate a specific knowledge node
   */
  async revalidateNode(nodeId: string): Promise<void> {
    return this.http.post(`/api/v1/knowledge/mound/revalidate/${nodeId}`, {});
  }

  // ===========================================================================
  // Federation
  // ===========================================================================

  /**
   * List federated regions
   */
  async listRegions(): Promise<FederationRegion[]> {
    return this.http.get('/api/v1/knowledge/mound/federation/regions');
  }

  /**
   * Register a new federated region
   */
  async registerRegion(name: string, endpoint: string): Promise<FederationRegion> {
    return this.http.post('/api/v1/knowledge/mound/federation/regions', { name, endpoint });
  }

  /**
   * Push sync to a specific region
   */
  async syncPush(regionId: string): Promise<SyncResult> {
    return this.http.post('/api/v1/knowledge/mound/federation/sync/push', { region_id: regionId });
  }

  /**
   * Pull sync from a specific region
   */
  async syncPull(regionId: string): Promise<SyncResult> {
    return this.http.post('/api/v1/knowledge/mound/federation/sync/pull', { region_id: regionId });
  }

  /**
   * Get federation status across all regions
   */
  async federationStatus(): Promise<unknown> {
    return this.http.get('/api/v1/knowledge/mound/federation/status');
  }

  // ===========================================================================
  // Checkpoints
  // ===========================================================================

  /**
   * List KM checkpoints
   */
  async listCheckpoints(): Promise<CheckpointListResponse> {
    return this.http.get('/api/v1/km/checkpoints');
  }

  /**
   * Create a new checkpoint
   */
  async createCheckpoint(name: string, description?: string): Promise<Checkpoint> {
    return this.http.post('/api/v1/km/checkpoints', { name, description });
  }

  /**
   * Restore from a checkpoint
   */
  async restoreCheckpoint(name: string, mode: 'merge' | 'replace' = 'merge'): Promise<void> {
    return this.http.post(`/api/v1/km/checkpoints/${name}/restore`, { mode });
  }

  // ===========================================================================
  // Contradictions
  // ===========================================================================

  /**
   * Trigger contradiction detection scan
   */
  async detectContradictions(): Promise<ContradictionResult[]> {
    return this.http.post('/api/v1/knowledge/mound/contradictions/detect', {});
  }

  /**
   * List unresolved contradictions
   */
  async listContradictions(): Promise<ContradictionResult[]> {
    return this.http.get('/api/v1/knowledge/mound/contradictions');
  }

  /**
   * Resolve a contradiction
   */
  async resolveContradiction(id: string, resolution: string, keepNodeId?: string): Promise<void> {
    return this.http.post(`/api/v1/knowledge/mound/contradictions/${id}/resolve`, {
      resolution,
      keep_node_id: keepNodeId,
    });
  }

  // ===========================================================================
  // Global Knowledge (Admin)
  // ===========================================================================

  /**
   * Store a verified global fact (admin only)
   */
  async storeGlobalFact(
    content: string,
    metadata?: Record<string, unknown>,
  ): Promise<KnowledgeNode> {
    return this.http.post('/api/v1/knowledge/mound/global', { content, metadata });
  }

  /**
   * Query global knowledge
   */
  async queryGlobal(query?: string): Promise<KnowledgeNode[]> {
    const params = query ? `?query=${encodeURIComponent(query)}` : '';
    return this.http.get(`/api/v1/knowledge/mound/global${params}`);
  }

  // ===========================================================================
  // Memory Sync
  // ===========================================================================

  /**
   * Sync knowledge from ContinuumMemory
   */
  async syncFromContinuum(): Promise<SyncResult> {
    return this.http.post('/api/v1/knowledge/mound/sync/continuum', {});
  }

  /**
   * Sync knowledge from ConsensusMemory
   */
  async syncFromConsensus(): Promise<SyncResult> {
    return this.http.post('/api/v1/knowledge/mound/sync/consensus', {});
  }
}
