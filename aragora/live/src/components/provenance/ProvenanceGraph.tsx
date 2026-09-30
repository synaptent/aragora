'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

// Node types in the provenance graph
type NodeType = 'question' | 'agent' | 'argument' | 'evidence' | 'vote' | 'consensus' | 'synthesis';

interface ProvenanceNode {
  id: string;
  type: NodeType;
  label: string;
  content: string;
  agent?: string;
  round?: number;
  confidence?: number;
  verified?: boolean;
  hash?: string;
  timestamp?: string;
  x?: number;
  y?: number;
  depth?: number;
}

interface ProvenanceEdge {
  id: string;
  source: string;
  target: string;
  type: 'supports' | 'contradicts' | 'synthesizes' | 'contributes' | 'leads_to';
  weight?: number;
}

interface ProvenanceGraphData {
  debate_id: string;
  nodes: ProvenanceNode[];
  edges: ProvenanceEdge[];
  metadata: {
    total_nodes: number;
    total_edges: number;
    max_depth: number;
    verified: boolean;
    status: string;
  };
}

interface ProvenanceGraphProps {
  debateId: string;
  apiBase?: string;
  width?: number;
  height?: number;
  viewMode?: 'graph' | 'timeline';
  onNodeClick?: (node: ProvenanceNode) => void;
  onExport?: () => void;
}

const NODE_COLORS: Record<NodeType, string> = {
  question: '#fbbf24', // amber
  agent: '#a855f7', // purple
  argument: '#3b82f6', // blue
  evidence: '#22c55e', // green
  vote: '#f97316', // orange
  consensus: '#00ff00', // acid green
  synthesis: '#06b6d4', // cyan
};

const EDGE_COLORS: Record<string, string> = {
  supports: '#22c55e',
  contradicts: '#ef4444',
  synthesizes: '#06b6d4',
  contributes: '#6b7280',
  leads_to: '#a855f7',
};

const NODE_RADIUS: Record<NodeType, number> = {
  question: 24,
  agent: 16,
  argument: 14,
  evidence: 12,
  vote: 10,
  consensus: 28,
  synthesis: 16,
};

const _NODE_ICONS: Record<NodeType, string> = {
  question: '?',
  agent: '',
  argument: '',
  evidence: '',
  vote: '',
  consensus: '',
  synthesis: '',
};

export function ProvenanceGraph({
  debateId,
  apiBase = API_BASE_URL,
  width = 900,
  height = 600,
  viewMode = 'graph',
  onNodeClick,
  onExport,
}: ProvenanceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<ProvenanceGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<ProvenanceNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<ProvenanceNode | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [zoom, _setZoom] = useState(1);
  const [pan, _setPan] = useState({ x: 0, y: 0 });

  // Fetch provenance data
  const fetchProvenance = useCallback(async () => {
    try {
      setLoading(true);
      const endpoint =
        viewMode === 'timeline'
          ? `${apiBase}/api/debates/${debateId}/provenance/timeline`
          : `${apiBase}/api/debates/${debateId}/provenance`;

      const response = await fetch(endpoint);

      if (!response.ok) {
        throw new Error('Failed to fetch provenance data');
      }

      const json = await response.json();

      if (!Array.isArray(json?.nodes) || json.nodes.length === 0) {
        setData(null);
      } else {
        const layoutData = layoutNodes(json, width, height);
        setData(layoutData);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load provenance');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, debateId, viewMode, width, height]);

  useEffect(() => {
    fetchProvenance();
  }, [fetchProvenance]);

  // Layout nodes hierarchically
  function layoutNodes(data: ProvenanceGraphData, w: number, h: number): ProvenanceGraphData {
    const nodes = [...data.nodes];
    const nodesByDepth: Map<number, ProvenanceNode[]> = new Map();

    // Group by depth
    nodes.forEach((node) => {
      const depth = node.depth ?? 0;
      if (!nodesByDepth.has(depth)) {
        nodesByDepth.set(depth, []);
      }
      nodesByDepth.get(depth)!.push(node);
    });

    // Position nodes
    const maxDepth = Math.max(...nodesByDepth.keys());
    const yStep = (h - 120) / (maxDepth || 1);

    nodesByDepth.forEach((depthNodes, depth) => {
      const xStep = (w - 100) / (depthNodes.length + 1);
      depthNodes.forEach((node, i) => {
        node.x = 50 + (i + 1) * xStep;
        node.y = 60 + depth * yStep;
      });
    });

    return { ...data, nodes };
  }

  // Toggle node expansion
  const toggleExpand = (nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  // Handle node click
  const handleNodeClick = (node: ProvenanceNode) => {
    setSelectedNode(node === selectedNode ? null : node);
    onNodeClick?.(node);
  };

  // Build node lookup for edge rendering
  const nodeMap = useMemo(() => {
    const map = new Map<string, ProvenanceNode>();
    data?.nodes.forEach((node) => map.set(node.id, node));
    return map;
  }, [data]);

  // Export handler
  const handleExport = async () => {
    if (onExport) {
      onExport();
      return;
    }

    try {
      const response = await fetch(
        `${apiBase}/api/debates/${debateId}/provenance/export?format=json`,
      );
      const exportData = await response.json();

      const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `provenance-${debateId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      logger.error('Failed to export provenance:', err);
    }
  };

  // Verify chain handler
  const handleVerify = async () => {
    try {
      const response = await fetch(`${apiBase}/api/debates/${debateId}/provenance/verify`);
      const result = await response.json();
      alert(
        result.chain_valid
          ? 'Provenance chain verified successfully!'
          : `Verification failed: ${result.errors?.join(', ') || 'Unknown error'}`,
      );
    } catch {
      alert('Failed to verify provenance chain');
    }
  };

  if (loading) {
    return (
      <div className="p-4 bg-[var(--bg)] border border-[var(--border)] rounded-lg">
        <div className="flex items-center justify-center" style={{ height }}>
          <div className="animate-spin text-[var(--acid-green)] text-xl mr-2"></div>
          <span className="text-[var(--text-muted)] text-sm font-theme-data">
            Loading provenance graph...
          </span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-4 bg-[var(--bg)] border border-red-500/30 rounded-lg">
        <div className="text-red-400 text-sm font-theme-data">{error}</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-4 bg-[var(--bg)] border border-[var(--border)] rounded-lg">
        <div className="text-center text-[var(--text-muted)] text-sm font-theme-data py-8">
          No provenance data available for this debate
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="text-lg"></span>
          <h3 className="text-sm font-theme-data font-bold text-[var(--text)] uppercase">
            Decision Provenance
          </h3>
          {data.metadata.verified && (
            <span className="px-2 py-0.5 text-xs bg-green-500/20 text-green-400 border border-green-500/50 rounded font-theme-data">
              VERIFIED
            </span>
          )}
          {data.metadata.status === 'demo' && (
            <span className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/50 rounded font-theme-data">
              DEMO
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleVerify}
            className="px-2 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/50 transition-colors"
          >
            VERIFY CHAIN
          </button>
          <button
            onClick={handleExport}
            className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            EXPORT
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 px-3 py-2 bg-[var(--surface)]/50 border-b border-[var(--border)] text-xs font-theme-data flex-wrap">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-[var(--text-muted)] capitalize">{type}</span>
          </span>
        ))}
      </div>

      {/* Graph SVG */}
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="bg-[var(--bg)]"
        style={{ cursor: 'grab' }}
      >
        <defs>
          {/* Arrow markers for edges */}
          {Object.entries(EDGE_COLORS).map(([type, color]) => (
            <marker
              key={type}
              id={`arrow-${type}`}
              markerWidth="10"
              markerHeight="7"
              refX="10"
              refY="3.5"
              orient="auto"
            >
              <polygon points="0 0, 10 3.5, 0 7" fill={color} />
            </marker>
          ))}

          {/* Glow filter for selected nodes */}
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {/* Edges */}
          {data.edges.map((edge) => {
            const source = nodeMap.get(edge.source);
            const target = nodeMap.get(edge.target);

            if (!source || !target) return null;

            const color = EDGE_COLORS[edge.type] || EDGE_COLORS.contributes;

            return (
              <line
                key={edge.id}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke={color}
                strokeWidth={edge.type === 'leads_to' ? 2 : 1.5}
                strokeOpacity={0.6}
                strokeDasharray={edge.type === 'contradicts' ? '4 2' : undefined}
                markerEnd={`url(#arrow-${edge.type})`}
              />
            );
          })}

          {/* Nodes */}
          {data.nodes.map((node) => {
            const radius = NODE_RADIUS[node.type] || 12;
            const color = NODE_COLORS[node.type] || '#6b7280';
            const isSelected = selectedNode?.id === node.id;
            const isHovered = hoveredNode?.id === node.id;
            const _isExpanded = expandedNodes.has(node.id);

            return (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                onClick={() => handleNodeClick(node)}
                onMouseEnter={() => setHoveredNode(node)}
                onMouseLeave={() => setHoveredNode(null)}
                onDoubleClick={() => toggleExpand(node.id)}
                style={{ cursor: 'pointer' }}
              >
                {/* Selection/hover ring */}
                {(isSelected || isHovered) && (
                  <circle
                    r={radius + 4}
                    fill="none"
                    stroke={isSelected ? '#fff' : color}
                    strokeWidth={2}
                    strokeDasharray={isSelected ? undefined : '4 2'}
                    opacity={0.8}
                  />
                )}

                {/* Verified indicator */}
                {node.verified && (
                  <circle
                    r={radius + 6}
                    fill="none"
                    stroke="#22c55e"
                    strokeWidth={1}
                    strokeDasharray="2 2"
                    opacity={0.5}
                  />
                )}

                {/* Main circle */}
                <circle
                  r={radius}
                  fill={color}
                  stroke={isSelected ? '#fff' : '#000'}
                  strokeWidth={isSelected ? 2 : 1}
                  opacity={0.9}
                  filter={isSelected ? 'url(#glow)' : undefined}
                />

                {/* Node icon/label */}
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={node.type === 'consensus' ? 14 : radius * 0.8}
                  fill="#fff"
                  fontFamily="monospace"
                  fontWeight="bold"
                >
                  {node.type === 'consensus'
                    ? ''
                    : node.type === 'question'
                      ? '?'
                      : node.type === 'agent'
                        ? node.agent?.[0].toUpperCase()
                        : node.type === 'evidence'
                          ? ''
                          : node.type === 'vote'
                            ? ''
                            : node.type === 'synthesis'
                              ? ''
                              : ''}
                </text>

                {/* Agent name label */}
                {node.agent && (
                  <text
                    y={radius + 14}
                    textAnchor="middle"
                    fontSize={10}
                    fill="#aaa"
                    fontFamily="monospace"
                  >
                    {node.agent}
                  </text>
                )}

                {/* Confidence indicator */}
                {node.confidence !== undefined && (
                  <text
                    y={radius + (node.agent ? 26 : 14)}
                    textAnchor="middle"
                    fontSize={9}
                    fill={
                      node.confidence >= 0.8
                        ? '#22c55e'
                        : node.confidence >= 0.5
                          ? '#fbbf24'
                          : '#ef4444'
                    }
                    fontFamily="monospace"
                  >
                    {Math.round(node.confidence * 100)}%
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Selected Node Details Panel */}
      {selectedNode && (
        <div className="absolute top-16 right-4 w-72 p-3 bg-[var(--surface)] border border-[var(--acid-green)]/30 rounded shadow-lg z-10">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: NODE_COLORS[selectedNode.type] }}
              />
              <span className="text-xs font-theme-data uppercase text-[var(--text-muted)]">
                {selectedNode.type}
              </span>
              {selectedNode.verified && <span className="text-green-400 text-xs"></span>}
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-[var(--text-muted)] hover:text-[var(--text)] text-xs"
            >
              [X]
            </button>
          </div>

          <h4 className="font-theme-data text-sm text-[var(--acid-green)] mb-2">
            {selectedNode.label}
          </h4>

          <p className="text-xs text-[var(--text)] leading-relaxed mb-3">{selectedNode.content}</p>

          <div className="space-y-1 text-xs font-theme-data text-[var(--text-muted)]">
            {selectedNode.agent && (
              <div className="flex justify-between">
                <span>Agent:</span>
                <span className="text-[var(--acid-cyan)]">{selectedNode.agent}</span>
              </div>
            )}
            {selectedNode.round !== undefined && (
              <div className="flex justify-between">
                <span>Round:</span>
                <span className="text-[var(--text)]">{selectedNode.round}</span>
              </div>
            )}
            {selectedNode.confidence !== undefined && (
              <div className="flex justify-between">
                <span>Confidence:</span>
                <span
                  className={
                    selectedNode.confidence >= 0.8
                      ? 'text-green-400'
                      : selectedNode.confidence >= 0.5
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }
                >
                  {Math.round(selectedNode.confidence * 100)}%
                </span>
              </div>
            )}
            {selectedNode.hash && (
              <div className="flex justify-between">
                <span>Hash:</span>
                <span className="text-[var(--text-muted)] truncate max-w-[120px]">
                  {selectedNode.hash}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Stats footer */}
      <div className="px-3 py-2 border-t border-[var(--border)] text-xs text-[var(--text-muted)] font-theme-data flex items-center justify-between">
        <div className="flex items-center gap-4">
          <span>
            {data.metadata.total_nodes} nodes | {data.metadata.total_edges} edges
          </span>
          <span>Depth: {data.metadata.max_depth}</span>
        </div>
        <span>Click nodes for details | Double-click to expand</span>
      </div>
    </div>
  );
}

export default ProvenanceGraph;
