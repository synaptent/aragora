'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface BeliefNode {
  id: string;
  claim_id: string;
  statement: string;
  author: string;
  centrality: number;
  is_crux?: boolean;
  crux_score?: number;
  entropy?: number;
  belief?: { true_prob: number; false_prob: number; uncertain_prob: number };
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface BeliefLink {
  source: string | BeliefNode;
  target: string | BeliefNode;
  weight: number;
  type: 'supports' | 'contradicts' | 'elaborates' | 'relates';
}

interface BeliefGraphData {
  nodes: BeliefNode[];
  links: BeliefLink[];
  metadata: { debate_id: string; total_claims: number; crux_count: number };
}

interface BeliefNetworkGraphProps {
  debateId: string;
  apiBase?: string;
  width?: number;
  height?: number;
}

const authorColors: Record<string, string> = {
  claude: '#a855f7',
  gpt4: '#22c55e',
  gemini: '#3b82f6',
  deepseek: '#f97316',
  mistral: '#ec4899',
  default: '#6b7280',
};

const linkColors: Record<string, string> = {
  supports: '#22c55e',
  contradicts: '#ef4444',
  elaborates: '#3b82f6',
  relates: '#6b7280',
};

export function BeliefNetworkGraph({
  debateId,
  apiBase = API_BASE_URL,
  width = 600,
  height = 400,
}: BeliefNetworkGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<BeliefGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<BeliefNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<BeliefNode | null>(null);
  const [simulation, setSimulation] = useState<BeliefNode[]>([]);

  const { tokens, isLoading: authLoading } = useAuth();

  const fetchGraph = useCallback(async () => {
    try {
      if (authLoading || !tokens?.access_token) {
        setLoading(false);
        setError('Login required to load belief network');
        return;
      }
      setLoading(true);
      const headers: HeadersInit = {};
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(
        `${apiBase}/api/belief-network/${debateId}/graph?include_cruxes=true`,
        { headers },
      );

      if (!response.ok) {
        throw new Error('Failed to fetch belief network');
      }

      const json = await response.json();
      setData(json);
      setError(null);

      // Initialize node positions
      if (json.nodes) {
        const initializedNodes = json.nodes.map((node: BeliefNode) => ({
          ...node,
          x: width / 2 + (Math.random() - 0.5) * 200,
          y: height / 2 + (Math.random() - 0.5) * 200,
          vx: 0,
          vy: 0,
        }));
        setSimulation(initializedNodes);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  }, [apiBase, debateId, height, tokens?.access_token, width, authLoading]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  // Simple force simulation
  useEffect(() => {
    if (!data || simulation.length === 0) return;

    const interval = setInterval(() => {
      setSimulation((nodes) => {
        const newNodes = nodes.map((node) => ({ ...node }));

        // Apply forces
        for (let i = 0; i < newNodes.length; i++) {
          const node = newNodes[i];

          // Center gravity
          node.vx = (node.vx || 0) + (width / 2 - (node.x || 0)) * 0.01;
          node.vy = (node.vy || 0) + (height / 2 - (node.y || 0)) * 0.01;

          // Repulsion between nodes
          for (let j = 0; j < newNodes.length; j++) {
            if (i === j) continue;
            const other = newNodes[j];
            const dx = (node.x || 0) - (other.x || 0);
            const dy = (node.y || 0) - (other.y || 0);
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const repulsion = 1000 / (dist * dist);
            node.vx = (node.vx || 0) + (dx / dist) * repulsion;
            node.vy = (node.vy || 0) + (dy / dist) * repulsion;
          }

          // Link attraction
          data.links.forEach((link) => {
            const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
            const targetId = typeof link.target === 'string' ? link.target : link.target.id;

            if (node.id === sourceId || node.id === targetId) {
              const other = newNodes.find((n) =>
                node.id === sourceId ? n.id === targetId : n.id === sourceId,
              );
              if (other) {
                const dx = (other.x || 0) - (node.x || 0);
                const dy = (other.y || 0) - (node.y || 0);
                const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const attraction = dist * 0.01 * (link.weight || 0.5);
                node.vx = (node.vx || 0) + (dx / dist) * attraction;
                node.vy = (node.vy || 0) + (dy / dist) * attraction;
              }
            }
          });

          // Damping and update position
          node.vx = (node.vx || 0) * 0.9;
          node.vy = (node.vy || 0) * 0.9;
          node.x = Math.max(50, Math.min(width - 50, (node.x || 0) + (node.vx || 0)));
          node.y = Math.max(50, Math.min(height - 50, (node.y || 0) + (node.vy || 0)));
        }

        return newNodes;
      });
    }, 50);

    // Stop after settling
    const timeout = setTimeout(() => clearInterval(interval), 5000);

    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- simulation.length is only used for early return, not as trigger
  }, [data, width, height]);

  // Build node lookup for link rendering
  const nodeMap = useMemo(() => {
    const map = new Map<string, BeliefNode>();
    simulation.forEach((node) => map.set(node.id, node));
    return map;
  }, [simulation]);

  const getNodeRadius = (node: BeliefNode): number => {
    const base = node.is_crux ? 20 : 12;
    return base + (node.centrality || 0) * 10;
  };

  const getNodeColor = (node: BeliefNode): string => {
    return authorColors[node.author] || authorColors.default;
  };

  if (loading) {
    return (
      <div className="p-4 bg-bg border border-border rounded-lg">
        <div className="flex items-center justify-center" style={{ height }}>
          <div className="animate-spin text-[var(--accent)] text-xl">⟳</div>
          <span className="ml-2 text-text-muted text-sm font-theme-data">
            Loading belief network...
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-bg border border-red-500/30 rounded-lg">
        <div className="text-red-400 text-sm font-theme-data">{error}</div>
      </div>
    );
  }

  if (!data || simulation.length === 0) {
    return (
      <div className="p-4 bg-bg border border-border rounded-lg">
        <div className="text-center text-text-muted text-sm font-theme-data py-8">
          No belief network data available for this debate
        </div>
      </div>
    );
  }

  return (
    <div className="bg-bg border border-border rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-lg">🧠</span>
          <h3 className="text-sm font-theme-data font-bold text-text uppercase">Belief Network</h3>
        </div>
        <div className="text-xs text-text-muted font-theme-data">
          {data.metadata.total_claims} claims | {data.metadata.crux_count} cruxes
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 px-3 py-2 bg-surface/50 border-b border-border text-xs font-theme-data">
        <span className="text-text-muted">Authors:</span>
        {Object.entries(authorColors)
          .slice(0, 5)
          .map(([author, color]) => (
            <span key={author} className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-text-muted">{author}</span>
            </span>
          ))}
      </div>

      {/* Graph SVG */}
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="bg-bg"
        style={{ cursor: 'default' }}
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="10"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
          </marker>
        </defs>

        {/* Links */}
        {data.links.map((link, i) => {
          const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
          const targetId = typeof link.target === 'string' ? link.target : link.target.id;
          const source = nodeMap.get(sourceId);
          const target = nodeMap.get(targetId);

          if (!source || !target) return null;

          return (
            <line
              key={i}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke={linkColors[link.type] || linkColors.relates}
              strokeWidth={1 + (link.weight || 0.5) * 2}
              strokeOpacity={0.6}
              markerEnd="url(#arrowhead)"
            />
          );
        })}

        {/* Nodes */}
        {simulation.map((node) => {
          const radius = getNodeRadius(node);
          const isSelected = selectedNode?.id === node.id;
          const isHovered = hoveredNode?.id === node.id;

          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              onClick={() => setSelectedNode(isSelected ? null : node)}
              onMouseEnter={() => setHoveredNode(node)}
              onMouseLeave={() => setHoveredNode(null)}
              style={{ cursor: 'pointer' }}
            >
              {/* Glow for crux nodes */}
              {node.is_crux && (
                <circle
                  r={radius + 4}
                  fill="none"
                  stroke="#fbbf24"
                  strokeWidth={2}
                  strokeDasharray="4 2"
                  opacity={0.6}
                />
              )}

              {/* Main circle */}
              <circle
                r={radius}
                fill={getNodeColor(node)}
                stroke={isSelected || isHovered ? '#fff' : 'transparent'}
                strokeWidth={2}
                opacity={0.9}
              />

              {/* Crux indicator */}
              {node.is_crux && (
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={radius * 0.8}
                  fill="white"
                >
                  ★
                </text>
              )}

              {/* Label */}
              {(isHovered || isSelected) && (
                <text
                  y={radius + 12}
                  textAnchor="middle"
                  className="text-xs font-theme-data fill-text"
                >
                  {node.author}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Selected node details */}
      {selectedNode && (
        <div className="p-3 border-t border-border bg-surface/50">
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              {selectedNode.is_crux && (
                <span className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/50 rounded font-theme-data">
                  CRUX
                </span>
              )}
              <span className="text-sm font-theme-data text-text">{selectedNode.author}</span>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-text-muted hover:text-text text-xs"
            >
              ✕
            </button>
          </div>

          <p className="text-sm text-text mb-2 line-clamp-3">{selectedNode.statement}</p>

          <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted">
            <span>
              Centrality:{' '}
              <span className="text-text">
                {((selectedNode.centrality || 0) * 100).toFixed(1)}%
              </span>
            </span>
            {selectedNode.crux_score !== undefined && (
              <span>
                Crux Score:{' '}
                <span className="text-yellow-400">
                  {(selectedNode.crux_score * 100).toFixed(1)}%
                </span>
              </span>
            )}
            {selectedNode.entropy !== undefined && (
              <span>
                Entropy:{' '}
                <span
                  className={
                    selectedNode.entropy > 0.7
                      ? 'text-red-400'
                      : selectedNode.entropy > 0.4
                        ? 'text-yellow-400'
                        : 'text-green-400'
                  }
                >
                  {selectedNode.entropy.toFixed(2)}
                </span>
              </span>
            )}
          </div>

          {selectedNode.belief && (
            <div className="mt-2 flex gap-2 text-xs font-theme-data">
              <span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">
                T: {(selectedNode.belief.true_prob * 100).toFixed(0)}%
              </span>
              <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
                F: {(selectedNode.belief.false_prob * 100).toFixed(0)}%
              </span>
              <span className="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                ?: {(selectedNode.belief.uncertain_prob * 100).toFixed(0)}%
              </span>
            </div>
          )}
        </div>
      )}

      {/* Help text */}
      <div className="px-3 py-2 border-t border-border text-xs text-text-muted font-theme-data">
        <span className="text-yellow-400">★ Cruxes</span> = High-impact claims | Node size =
        centrality | Click nodes for details
      </div>
    </div>
  );
}

export default BeliefNetworkGraph;
