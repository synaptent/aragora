/**
 * Types for Knowledge Explorer Store
 */

export type NodeType = 'fact' | 'claim' | 'memory' | 'evidence' | 'consensus' | 'entity';
export type RelationshipType =
  'supports' | 'contradicts' | 'derived_from' | 'related_to' | 'supersedes';
export type MemoryTier = 'fast' | 'medium' | 'slow' | 'glacial';
export type SortField = 'created' | 'confidence' | 'accessed' | 'relevance';

export interface ProvenanceInfo {
  source_type: 'debate' | 'document' | 'user' | 'agent' | 'import';
  source_id?: string;
  debate_id?: string;
  document_id?: string;
  agent_name?: string;
  created_at: string;
}

export interface KnowledgeNode {
  id: string;
  node_type: NodeType;
  content: string;
  confidence: number;
  tier: MemoryTier;
  workspace_id: string;
  topics: string[];
  metadata: Record<string, unknown>;
  provenance?: ProvenanceInfo;
  created_at: string;
  accessed_at?: string;
  staleness_score?: number;
}

export interface KnowledgeRelationship {
  id: string;
  from_node_id: string;
  to_node_id: string;
  relationship_type: RelationshipType;
  strength: number;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface GraphNode extends KnowledgeNode {
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
  depth?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: RelationshipType;
  strength: number;
}

export interface NodeFilters {
  nodeTypes: NodeType[];
  minConfidence: number;
  tier: MemoryTier | null;
  workspace: string;
  topics: string[];
  dateFrom?: string;
  dateTo?: string;
}

export interface QueryResult {
  nodes: KnowledgeNode[];
  total: number;
  took_ms: number;
}

export interface GraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  root_id: string;
  depth: number;
}

export interface StaleNodeInfo {
  id: string;
  content: string;
  node_type: NodeType;
  confidence: number;
  staleReason: string;
  lastValidated?: string;
  daysStale: number;
}

export interface MoundStats {
  total_nodes: number;
  nodes_by_type: Record<NodeType, number>;
  nodes_by_tier: Record<MemoryTier, number>;
  total_relationships: number;
  avg_confidence: number;
  stale_nodes_count: number;
  stale_nodes?: StaleNodeInfo[];
}

// Store State Types

export interface QueryState {
  text: string;
  isExecuting: boolean;
  results: KnowledgeNode[];
  total: number;
  error: string | null;
}

export interface BrowserState {
  nodes: KnowledgeNode[];
  totalNodes: number;
  selectedNodeId: string | null;
  filters: NodeFilters;
  sortBy: SortField;
  sortDirection: 'asc' | 'desc';
  page: number;
  pageSize: number;
  isLoading: boolean;
  error: string | null;
}

export interface GraphState {
  rootNodeId: string | null;
  depth: number;
  direction: 'outgoing' | 'incoming' | 'both';
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  hoveredNodeId: string | null;
  isLoading: boolean;
  error: string | null;
  zoom: number;
  panX: number;
  panY: number;
}

export interface DetailPanelState {
  isOpen: boolean;
  nodeId: string | null;
  node: KnowledgeNode | null;
  relationships: KnowledgeRelationship[];
  isLoading: boolean;
}

export interface RelationshipEditorState {
  isOpen: boolean;
  fromNodeId: string | null;
  toNodeId: string | null;
  editingRelationship: KnowledgeRelationship | null;
}

export interface NodeEditorState {
  isOpen: boolean;
  editingNode: KnowledgeNode | null;
  isNew: boolean;
}

export interface KnowledgeExplorerState {
  query: QueryState;
  browser: BrowserState;
  graph: GraphState;
  detailPanel: DetailPanelState;
  relationshipEditor: RelationshipEditorState;
  nodeEditor: NodeEditorState;
  stats: MoundStats | null;
  statsLoading: boolean;
  activeTab:
    | 'search'
    | 'browse'
    | 'graph'
    | 'stale'
    | 'shared'
    | 'federation'
    | 'quality'
    | 'adapters'
    | 'contradictions';
}

export interface KnowledgeExplorerActions {
  // Query operations
  setQueryText: (text: string) => void;
  setQueryExecuting: (executing: boolean) => void;
  setQueryResults: (results: KnowledgeNode[], total?: number) => void;
  setQueryError: (error: string | null) => void;
  clearQueryResults: () => void;

  // Browser operations
  setBrowserNodes: (nodes: KnowledgeNode[], total?: number) => void;
  setBrowserLoading: (loading: boolean) => void;
  setBrowserError: (error: string | null) => void;
  selectBrowserNode: (id: string | null) => void;
  setFilters: (filters: Partial<NodeFilters>) => void;
  resetFilters: () => void;
  setSortBy: (field: SortField) => void;
  toggleSortDirection: () => void;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;

  // Graph operations
  setGraphRoot: (nodeId: string | null) => void;
  setGraphDepth: (depth: number) => void;
  setGraphDirection: (direction: 'outgoing' | 'incoming' | 'both') => void;
  setGraphData: (nodes: GraphNode[], edges: GraphEdge[]) => void;
  setGraphLoading: (loading: boolean) => void;
  setGraphError: (error: string | null) => void;
  selectGraphNode: (id: string | null) => void;
  hoverGraphNode: (id: string | null) => void;
  setGraphZoom: (zoom: number) => void;
  setGraphPan: (x: number, y: number) => void;
  updateNodePosition: (id: string, x: number, y: number) => void;
  clearGraph: () => void;

  // Detail panel operations
  openDetailPanel: (nodeId: string) => void;
  closeDetailPanel: () => void;
  setDetailNode: (node: KnowledgeNode | null) => void;
  setDetailRelationships: (relationships: KnowledgeRelationship[]) => void;
  setDetailLoading: (loading: boolean) => void;

  // Relationship editor operations
  openRelationshipEditor: (fromId: string, toId?: string | null) => void;
  closeRelationshipEditor: () => void;
  setEditingRelationship: (relationship: KnowledgeRelationship | null) => void;

  // Node editor operations
  openNodeEditor: (node?: KnowledgeNode | null) => void;
  closeNodeEditor: () => void;

  // Statistics
  setStats: (stats: MoundStats | null) => void;
  setStatsLoading: (loading: boolean) => void;

  // Tab navigation
  setActiveTab: (
    tab:
      | 'search'
      | 'browse'
      | 'graph'
      | 'stale'
      | 'shared'
      | 'federation'
      | 'quality'
      | 'adapters'
      | 'contradictions',
  ) => void;

  // Reset
  resetExplorer: () => void;
}

export type KnowledgeExplorerStore = KnowledgeExplorerState & KnowledgeExplorerActions;
