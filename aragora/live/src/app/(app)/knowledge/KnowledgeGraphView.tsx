'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';
import type { KnowledgeNode, KnowledgeRelationship } from './types';
import type {
  GraphNode,
  GraphEdge,
  NodeType,
  RelationshipType,
} from '@/store/knowledge-explorer/types';
import { GraphViewer } from '@/components/control-plane/KnowledgeExplorer/GraphViewer';
import { logger } from '@/utils/logger';

// API response types for D3 graph export
interface ApiNode {
  id?: string;
  type?: string;
  node_type?: string;
  content?: string;
  label?: string;
  confidence?: number;
  tier?: string;
  topics?: string[];
  metadata?: Record<string, unknown>;
  created_at?: string;
  x?: number;
  y?: number;
  depth?: number;
}

interface ApiLink {
  id?: string;
  source: string | { id: string };
  target: string | { id: string };
  type?: string;
  relationship_type?: string;
  strength?: number;
  value?: number;
}

export interface KnowledgeGraphViewProps {
  /** Initial nodes to display (from parent) */
  nodes: KnowledgeNode[];
  /** Currently selected node */
  selectedNode: KnowledgeNode | null;
  /** Callback when node is selected */
  onNodeSelect: (node: KnowledgeNode | null) => void;
  /** Search query to filter graph */
  searchQuery?: string;
}

/**
 * Transform knowledge page node to graph node format.
 * Converts camelCase properties to snake_case for GraphViewer compatibility.
 */
function transformToGraphNode(node: KnowledgeNode, index: number): GraphNode {
  return {
    id: node.id,
    node_type: node.nodeType as NodeType,
    content: node.content,
    confidence: node.confidence,
    tier: node.tier as 'fast' | 'medium' | 'slow' | 'glacial',
    workspace_id: 'default',
    topics: node.topics || [],
    metadata: node.metadata || {},
    provenance: node.debateId
      ? { source_type: 'debate', debate_id: node.debateId, created_at: node.createdAt }
      : node.documentId
        ? { source_type: 'document', document_id: node.documentId, created_at: node.createdAt }
        : node.agentId
          ? { source_type: 'agent', agent_name: node.agentId, created_at: node.createdAt }
          : { source_type: 'user', created_at: node.createdAt },
    created_at: node.createdAt,
    accessed_at: node.updatedAt,
    // Initial position spread in a circle
    x: 400 + Math.cos((index / 10) * Math.PI * 2) * 200,
    y: 250 + Math.sin((index / 10) * Math.PI * 2) * 150,
    depth: 0,
  };
}

/**
 * Transform relationship to graph edge format.
 */
function _transformToGraphEdge(rel: KnowledgeRelationship): GraphEdge {
  // Map relationship types to valid GraphEdge types
  const typeMap: Record<string, RelationshipType> = {
    supports: 'supports',
    contradicts: 'contradicts',
    derived_from: 'derived_from',
    references: 'related_to',
    related_to: 'related_to',
    supersedes: 'supersedes',
  };

  return {
    id: rel.id,
    source: rel.sourceId,
    target: rel.targetId,
    type: typeMap[rel.relationshipType] || 'related_to',
    strength: rel.strength,
  };
}

/**
 * Knowledge Graph View component.
 * Displays knowledge nodes as an interactive force-directed graph.
 */
export function KnowledgeGraphView({
  nodes,
  selectedNode,
  onNodeSelect,
  searchQuery,
}: KnowledgeGraphViewProps) {
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch graph data from API
  const fetchGraphData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Try to get graph export for visualization
      const response = await fetch(`${API_BASE_URL}/api/knowledge/mound/export/d3`);

      if (response.ok) {
        const data = await response.json();
        // D3 format has nodes and links arrays
        if (data.nodes && Array.isArray(data.nodes)) {
          // Transform API nodes to GraphNode format
          const apiGraphNodes: GraphNode[] = (data.nodes as ApiNode[]).map((n, i) => ({
            id: n.id || `node-${i}`,
            node_type: (n.type || n.node_type || 'fact') as NodeType,
            content: n.content || n.label || n.id || '',
            confidence: n.confidence || 0.5,
            tier: (n.tier || 'medium') as 'fast' | 'medium' | 'slow' | 'glacial',
            workspace_id: 'default',
            topics: n.topics || [],
            metadata: n.metadata || {},
            created_at: n.created_at || new Date().toISOString(),
            x: n.x,
            y: n.y,
            depth: n.depth || 0,
          }));

          const apiGraphEdges: GraphEdge[] = ((data.links || data.edges || []) as ApiLink[]).map(
            (l, i) => ({
              id: l.id || `edge-${i}`,
              source: typeof l.source === 'object' ? l.source.id : l.source,
              target: typeof l.target === 'object' ? l.target.id : l.target,
              type: (l.type || l.relationship_type || 'related_to') as RelationshipType,
              strength: l.strength || l.value || 0.5,
            }),
          );

          setGraphNodes(apiGraphNodes);
          setGraphEdges(apiGraphEdges);
          return;
        }
      }

      // Fallback: Transform the nodes passed from parent
      if (nodes.length > 0) {
        const transformed = nodes.map((n, i) => transformToGraphNode(n, i));
        setGraphNodes(transformed);

        // Fetch relationships for each node
        const allEdges: GraphEdge[] = [];
        const seenEdges = new Set<string>();

        for (const node of nodes.slice(0, 20)) {
          try {
            const relResponse = await fetch(
              `${API_BASE_URL}/api/knowledge/mound/nodes/${node.id}/relationships`,
            );
            if (relResponse.ok) {
              const relData = await relResponse.json();
              const relationships = relData.relationships || [];
              for (const rel of relationships) {
                const edgeKey = `${rel.sourceId || rel.source_id}-${rel.targetId || rel.target_id}`;
                if (!seenEdges.has(edgeKey)) {
                  seenEdges.add(edgeKey);
                  allEdges.push({
                    id: rel.id,
                    source: rel.sourceId || rel.source_id,
                    target: rel.targetId || rel.target_id,
                    type: (rel.relationshipType ||
                      rel.relationship_type ||
                      'related_to') as RelationshipType,
                    strength: rel.strength || 0.5,
                  });
                }
              }
            }
          } catch {
            // Continue with other nodes
          }
        }

        setGraphEdges(allEdges);
      }
    } catch (err) {
      logger.error('Failed to fetch graph data:', err);
      setError('Failed to load graph data');

      // Use transformed parent nodes as fallback
      if (nodes.length > 0) {
        setGraphNodes(nodes.map((n, i) => transformToGraphNode(n, i)));
        setGraphEdges([]);
      }
    } finally {
      setLoading(false);
    }
  }, [nodes]);

  // Fetch graph data on mount and when nodes change
  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  // Handle node click - find original node and pass to parent
  const handleNodeClick = useCallback(
    (graphNode: GraphNode) => {
      // Find the original knowledge node
      const originalNode = nodes.find((n) => n.id === graphNode.id);
      if (originalNode) {
        onNodeSelect(originalNode);
      } else {
        // Create a temporary node from graph node
        onNodeSelect({
          id: graphNode.id,
          nodeType: graphNode.node_type,
          content: graphNode.content,
          confidence: graphNode.confidence,
          tier: graphNode.tier,
          sourceType: graphNode.provenance?.source_type || 'unknown',
          topics: graphNode.topics,
          createdAt: graphNode.created_at,
          updatedAt: graphNode.accessed_at || graphNode.created_at,
          metadata: graphNode.metadata,
          debateId: graphNode.provenance?.debate_id,
          documentId: graphNode.provenance?.document_id,
          agentId: graphNode.provenance?.agent_name,
        });
      }
    },
    [nodes, onNodeSelect],
  );

  // Handle node hover
  const handleNodeHover = useCallback((nodeId: string | null) => {
    setHoveredNodeId(nodeId);
  }, []);

  // Filter nodes if search query is provided
  const filteredNodes = useMemo(() => {
    if (!searchQuery) return graphNodes;
    const query = searchQuery.toLowerCase();
    return graphNodes.filter(
      (n) =>
        n.content.toLowerCase().includes(query) ||
        n.topics.some((t) => t.toLowerCase().includes(query)),
    );
  }, [graphNodes, searchQuery]);

  // Filter edges to only include those between filtered nodes
  const filteredEdges = useMemo(() => {
    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    return graphEdges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
  }, [graphEdges, filteredNodes]);

  if (error && graphNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-[500px] bg-surface border border-border rounded-lg">
        <div className="text-center">
          <div className="text-4xl mb-2">⚠️</div>
          <p className="text-text-muted text-sm">{error}</p>
          <button
            onClick={fetchGraphData}
            className="mt-3 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] text-sm font-theme-data rounded hover:bg-[var(--accent)]/30"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Graph header */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-theme-data text-text-muted">
          {filteredNodes.length} nodes • {filteredEdges.length} relationships
        </div>
        <button
          onClick={fetchGraphData}
          disabled={loading}
          className="px-3 py-1 text-xs font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Graph viewer */}
      <GraphViewer
        nodes={filteredNodes}
        edges={filteredEdges}
        selectedNodeId={selectedNode?.id || null}
        hoveredNodeId={hoveredNodeId}
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        width={800}
        height={500}
        loading={loading}
        showLabels={true}
      />

      {/* Hovered node tooltip */}
      {hoveredNodeId && !selectedNode && (
        <div className="absolute bottom-14 left-2 bg-bg/95 border border-border rounded p-2 max-w-xs z-10">
          {(() => {
            const hoveredNode = filteredNodes.find((n) => n.id === hoveredNodeId);
            if (!hoveredNode) return null;
            return (
              <>
                <div className="text-xs font-theme-data text-[var(--accent)] mb-1">
                  {hoveredNode.node_type.toUpperCase()}
                </div>
                <div className="text-xs text-text line-clamp-2">{hoveredNode.content}</div>
                <div className="text-xs text-text-muted mt-1">
                  Confidence: {Math.round(hoveredNode.confidence * 100)}%
                </div>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}

export default KnowledgeGraphView;
