/**
 * TypeScript types for Knowledge Mound features.
 *
 * These types correspond to the backend schemas in:
 * - aragora/knowledge/mound/types.py
 * - aragora/knowledge/mound/ops/global_knowledge.py
 * - aragora/knowledge/mound/ops/sharing.py
 * - aragora/knowledge/mound/ops/federation.py
 *
 * Auto-generated types can be regenerated but these manual types provide
 * additional documentation and better integration with React components.
 */

// =============================================================================
// Core Types
// =============================================================================

/**
 * Visibility level for knowledge items.
 * Controls who can access the item.
 */
export type VisibilityLevel =
  | 'private' // Creator and explicit grantees only
  | 'workspace' // All workspace members (default)
  | 'organization' // All organization members
  | 'public' // Unauthenticated access
  | 'system'; // System-wide verified facts (global knowledge)

/**
 * Type of access grant recipient.
 */
export type AccessGrantType = 'user' | 'role' | 'workspace' | 'organization';

/**
 * Permission levels for access grants.
 */
export type Permission = 'read' | 'write' | 'admin' | 'share';

/**
 * Confidence level for knowledge items.
 */
export type ConfidenceLevel = 'verified' | 'high' | 'medium' | 'low' | 'speculative';

/**
 * Knowledge tier (lifecycle/importance).
 */
export type KnowledgeTier = 'ephemeral' | 'session' | 'persistent' | 'glacial';

/**
 * Type of knowledge node.
 */
export type NodeType = 'fact' | 'concept' | 'claim' | 'evidence' | 'relationship' | 'summary';

/**
 * Source type for knowledge.
 */
export type KnowledgeSource =
  'conversation' | 'debate' | 'document' | 'web' | 'user_input' | 'system' | 'fact';

// =============================================================================
// Knowledge Items
// =============================================================================

/**
 * A knowledge item from the mound.
 */
export interface KnowledgeItem {
  id: string;
  content: string;
  nodeType: NodeType;
  tier: KnowledgeTier;
  source: KnowledgeSource;
  workspaceId: string;
  confidence: ConfidenceLevel | number;
  importance?: number;
  topics?: string[];
  metadata?: Record<string, unknown>;
  createdAt: string;
  updatedAt?: string;
  expiresAt?: string;

  // Visibility fields
  visibility: VisibilityLevel;
  visibilitySetBy?: string;
  isDiscoverable: boolean;

  // Relationships
  parentId?: string;
  childIds?: string[];
  relatedIds?: string[];
}

/**
 * Request to create/update a knowledge item.
 */
export interface KnowledgeItemRequest {
  content: string;
  nodeType?: NodeType;
  tier?: KnowledgeTier;
  source?: KnowledgeSource;
  workspaceId?: string;
  confidence?: number;
  topics?: string[];
  metadata?: Record<string, unknown>;
  visibility?: VisibilityLevel;
  isDiscoverable?: boolean;
  parentId?: string;
}

/**
 * Query filters for knowledge items.
 */
export interface KnowledgeQueryFilters {
  nodeTypes?: NodeType[];
  tiers?: KnowledgeTier[];
  sources?: KnowledgeSource[];
  minConfidence?: ConfidenceLevel | number;
  maxConfidence?: ConfidenceLevel | number;
  tags?: string[];
  visibilityLevels?: VisibilityLevel[];
  updatedSince?: string;
  updatedBefore?: string;
}

/**
 * Response from a knowledge query.
 */
export interface KnowledgeQueryResult {
  items: KnowledgeItem[];
  count: number;
  total?: number;
  hasMore?: boolean;
  nextCursor?: string;
}

// =============================================================================
// Access Control & Visibility
// =============================================================================

/**
 * Access grant for a knowledge item.
 */
export interface AccessGrant {
  id: string;
  itemId: string;
  granteeType: AccessGrantType;
  granteeId: string;
  permissions: Permission[];
  grantedBy?: string;
  grantedAt: string;
  expiresAt?: string;
}

/**
 * Request to grant access.
 */
export interface AccessGrantRequest {
  granteeType: AccessGrantType;
  granteeId: string;
  permissions?: Permission[];
  expiresAt?: string;
}

/**
 * Request to set item visibility.
 */
export interface SetVisibilityRequest {
  visibility: VisibilityLevel;
  isDiscoverable?: boolean;
}

/**
 * Response from visibility operations.
 */
export interface VisibilityResponse {
  itemId: string;
  visibility: VisibilityLevel;
  visibilitySetBy?: string;
  isDiscoverable: boolean;
}

// =============================================================================
// Sharing
// =============================================================================

/**
 * Target type for sharing.
 */
export type ShareTargetType = 'workspace' | 'user';

/**
 * Request to share an item.
 */
export interface ShareItemRequest {
  itemId: string;
  targetType: ShareTargetType;
  targetId: string;
  permissions?: Permission[];
  fromWorkspaceId?: string;
  expiresAt?: string;
  message?: string;
}

/**
 * A share grant (item shared with workspace/user).
 */
export interface ShareGrant {
  id: string;
  itemId: string;
  item?: KnowledgeItem;
  targetType: ShareTargetType;
  targetId: string;
  targetName?: string;
  permissions: Permission[];
  sharedBy: string;
  sharedByName?: string;
  sharedAt: string;
  expiresAt?: string;
  message?: string;
}

/**
 * Item shared with the current user/workspace.
 */
export interface SharedItem {
  id: string;
  content: string;
  nodeType: NodeType;
  sharedBy: string;
  sharedByName?: string;
  sharedAt: string;
  permissions: Permission[];
  sourceWorkspace?: string;
  sourceWorkspaceName?: string;
}

/**
 * Response from shared-with-me endpoint.
 */
export interface SharedWithMeResponse {
  items: SharedItem[];
  count: number;
  limit: number;
  offset: number;
}

// =============================================================================
// Global Knowledge
// =============================================================================

/**
 * A verified fact in the global knowledge mound.
 */
export interface VerifiedFact extends KnowledgeItem {
  source: 'fact' | 'system';
  verifiedBy?: string;
  verifiedAt?: string;
  evidenceIds?: string[];
}

/**
 * Request to store a verified fact.
 */
export interface StoreVerifiedFactRequest {
  content: string;
  source: string;
  confidence?: number;
  evidenceIds?: string[];
  topics?: string[];
}

/**
 * Request to promote an item to global.
 */
export interface PromoteToGlobalRequest {
  itemId: string;
  workspaceId: string;
  reason: string;
  additionalEvidence?: string[];
}

/**
 * Response from global knowledge query.
 */
export interface GlobalKnowledgeResponse {
  items: VerifiedFact[];
  count: number;
  query?: string;
}

// =============================================================================
// Federation
// =============================================================================

/**
 * Sync mode for federated regions.
 */
export type SyncMode = 'push' | 'pull' | 'bidirectional' | 'none';

/**
 * Sync scope for federated regions.
 */
export type SyncScope = 'full' | 'metadata' | 'summary';

/**
 * Health status of a federated region.
 */
export type RegionHealth = 'healthy' | 'degraded' | 'offline' | 'unknown';

/**
 * A federated region for knowledge sync.
 */
export interface FederatedRegion {
  id: string;
  name: string;
  endpointUrl: string;
  mode: SyncMode;
  scope: SyncScope;
  enabled: boolean;
  health: RegionHealth;
  lastSyncAt?: Date | string;
  lastSyncError?: string;
  nodesSynced?: number;
  pendingSync?: number;
}

/**
 * Request to register a federated region.
 */
export interface RegisterRegionRequest {
  regionId: string;
  name?: string;
  endpointUrl: string;
  apiKey: string;
  mode?: SyncMode;
  syncScope?: SyncScope;
}

/**
 * Form data for region dialog.
 */
export interface RegionFormData {
  name: string;
  regionId: string;
  endpointUrl: string;
  apiKey: string;
  mode: SyncMode;
  scope: SyncScope;
  enabled: boolean;
}

/**
 * Request to sync with a region.
 */
export interface SyncRegionRequest {
  regionId: string;
  workspaceId?: string;
  since?: string;
  visibilityLevels?: VisibilityLevel[];
}

/**
 * Result of a sync operation.
 */
export interface SyncResult {
  success: boolean;
  regionId: string;
  direction: 'push' | 'pull';
  nodesSynced: number;
  nodesSkipped?: number;
  nodesFailed: number;
  durationMs: number;
  error?: string;
}

/**
 * Federation status response.
 */
export interface FederationStatus {
  regions: Record<string, FederatedRegion>;
  totalRegions: number;
  enabledRegions: number;
}

// =============================================================================
// API Responses
// =============================================================================

/**
 * Standard success response.
 */
export interface SuccessResponse {
  success: true;
  message?: string;
}

/**
 * Standard error response.
 */
export interface ErrorResponse {
  success: false;
  error: string;
  code?: string;
  details?: Record<string, unknown>;
}

/**
 * Paginated response wrapper.
 */
export interface PaginatedResponse<T> {
  items: T[];
  count: number;
  total?: number;
  limit: number;
  offset: number;
  hasMore?: boolean;
}

// =============================================================================
// API Client Types
// =============================================================================

/**
 * Knowledge Mound API endpoints.
 */
export interface KnowledgeMoundApi {
  // Visibility
  getVisibility(nodeId: string): Promise<VisibilityResponse>;
  setVisibility(nodeId: string, request: SetVisibilityRequest): Promise<VisibilityResponse>;

  // Access Grants
  grantAccess(nodeId: string, request: AccessGrantRequest): Promise<AccessGrant>;
  revokeAccess(nodeId: string, granteeId: string): Promise<SuccessResponse>;
  listAccessGrants(nodeId: string): Promise<{ grants: AccessGrant[]; count: number }>;

  // Sharing
  shareItem(request: ShareItemRequest): Promise<ShareGrant>;
  revokeShare(itemId: string, granteeId: string): Promise<SuccessResponse>;
  getSharedWithMe(
    workspaceId: string,
    options?: { limit?: number; offset?: number },
  ): Promise<SharedWithMeResponse>;
  getMyShares(
    workspaceId: string,
    options?: { limit?: number; offset?: number },
  ): Promise<{ grants: ShareGrant[]; count: number }>;

  // Global Knowledge
  storeVerifiedFact(request: StoreVerifiedFactRequest): Promise<{ nodeId: string }>;
  queryGlobalKnowledge(
    query: string,
    options?: { limit?: number; topics?: string[] },
  ): Promise<GlobalKnowledgeResponse>;
  promoteToGlobal(request: PromoteToGlobalRequest): Promise<{ globalId: string }>;
  getSystemFacts(options?: {
    limit?: number;
    offset?: number;
    topics?: string[];
  }): Promise<PaginatedResponse<VerifiedFact>>;
  getSystemWorkspaceId(): Promise<{ systemWorkspaceId: string }>;

  // Federation
  registerRegion(request: RegisterRegionRequest): Promise<FederatedRegion>;
  unregisterRegion(regionId: string): Promise<SuccessResponse>;
  listRegions(): Promise<{ regions: FederatedRegion[]; count: number }>;
  syncToRegion(request: SyncRegionRequest): Promise<SyncResult>;
  pullFromRegion(request: SyncRegionRequest): Promise<SyncResult>;
  syncAllRegions(options?: {
    workspaceId?: string;
    since?: string;
  }): Promise<{ results: SyncResult[] }>;
  getFederationStatus(): Promise<FederationStatus>;
}
