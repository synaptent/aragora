'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

/* ------------------------------------------------------------------ */
/*  Types matching the server's ArgumentCartographer JSON output       */
/* ------------------------------------------------------------------ */

interface GraphNode {
  id: string;
  agent: string;
  node_type:
    'proposal' | 'critique' | 'evidence' | 'concession' | 'rebuttal' | 'vote' | 'consensus';
  summary: string;
  round_num: number;
  timestamp?: number;
  metadata?: Record<string, unknown>;
}

interface GraphEdge {
  source_id: string;
  target_id: string;
  relation: 'supports' | 'refutes' | 'modifies' | 'responds_to' | 'concedes_to';
  weight?: number;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/* ------------------------------------------------------------------ */
/*  Color mapping                                                      */
/* ------------------------------------------------------------------ */

const NODE_COLORS: Record<string, string> = {
  proposal: 'var(--acid-green)',
  critique: 'var(--warning, #f59e0b)',
  evidence: 'var(--acid-cyan)',
  concession: '#a78bfa',
  rebuttal: '#f87171',
  vote: '#60a5fa',
  consensus: '#34d399',
};

const EDGE_COLORS: Record<string, string> = {
  supports: '#34d399',
  refutes: '#f87171',
  modifies: '#fbbf24',
  responds_to: '#94a3b8',
  concedes_to: '#a78bfa',
};

/* ------------------------------------------------------------------ */
/*  Simple force-directed layout (no external deps)                    */
/* ------------------------------------------------------------------ */

interface LayoutNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  data: GraphNode;
}

function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
): LayoutNode[] {
  const layout: LayoutNode[] = nodes.map((n, i) => ({
    id: n.id,
    x: width / 2 + Math.cos((i / nodes.length) * Math.PI * 2) * width * 0.35,
    y: height / 2 + Math.sin((i / nodes.length) * Math.PI * 2) * height * 0.35,
    vx: 0,
    vy: 0,
    data: n,
  }));

  const idxMap = new Map(layout.map((n, i) => [n.id, i]));

  // Run 80 iterations of simple force simulation
  for (let iter = 0; iter < 80; iter++) {
    const alpha = 1 - iter / 80;

    // Repulsion between all pairs
    for (let i = 0; i < layout.length; i++) {
      for (let j = i + 1; j < layout.length; j++) {
        const dx = layout[j].x - layout[i].x;
        const dy = layout[j].y - layout[i].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const force = (200 * alpha) / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        layout[i].vx -= fx;
        layout[i].vy -= fy;
        layout[j].vx += fx;
        layout[j].vy += fy;
      }
    }

    // Attraction along edges
    for (const edge of edges) {
      const si = idxMap.get(edge.source_id);
      const ti = idxMap.get(edge.target_id);
      if (si === undefined || ti === undefined) continue;
      const dx = layout[ti].x - layout[si].x;
      const dy = layout[ti].y - layout[si].y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const force = (dist - 120) * 0.03 * alpha;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      layout[si].vx += fx;
      layout[si].vy += fy;
      layout[ti].vx -= fx;
      layout[ti].vy -= fy;
    }

    // Center gravity
    for (const node of layout) {
      node.vx += (width / 2 - node.x) * 0.01 * alpha;
      node.vy += (height / 2 - node.y) * 0.01 * alpha;
    }

    // Apply velocities with damping
    for (const node of layout) {
      node.vx *= 0.6;
      node.vy *= 0.6;
      node.x += node.vx;
      node.y += node.vy;
      // Keep within bounds
      node.x = Math.max(40, Math.min(width - 40, node.x));
      node.y = Math.max(40, Math.min(height - 40, node.y));
    }
  }

  return layout;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function ArgumentGraph({ debateId }: { debateId: string }) {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const WIDTH = 800;
  const HEIGHT = 500;

  useEffect(() => {
    async function fetchGraph() {
      try {
        setLoading(true);
        const res = await fetch(
          `${API_BASE_URL}/api/v1/debates/${debateId}/argument-graph?format=json`,
        );
        if (!res.ok) {
          if (res.status === 503) {
            setError('Graph analysis module not available on this server.');
          } else if (res.status === 404) {
            setError('No argument trace found for this debate.');
          } else {
            setError(`Failed to load graph (HTTP ${res.status})`);
          }
          return;
        }
        const data = await res.json();
        setGraph(data.graph);
      } catch (e) {
        logger.error('Failed to fetch argument graph:', e);
        setError('Network error loading graph.');
      } finally {
        setLoading(false);
      }
    }

    if (debateId) fetchGraph();
  }, [debateId]);

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="text-[var(--acid-green)] font-theme-data animate-pulse text-sm">
          {'>'} BUILDING ARGUMENT GRAPH...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12 text-[var(--text-muted)] font-theme-data text-sm">
        {'>'} {error}
      </div>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="text-center py-12 text-[var(--text-muted)] font-theme-data text-sm">
        {'>'} No argument structure available for this debate.
      </div>
    );
  }

  const layoutNodes = layoutGraph(graph.nodes, graph.edges, WIDTH, HEIGHT);
  const nodeMap = new Map(layoutNodes.map((n) => [n.id, n]));

  // Find connected edges for hovered/selected node
  const highlightEdges = new Set<string>();
  const activeId = selectedNode?.id ?? hoveredNode;
  if (activeId) {
    for (const edge of graph.edges) {
      if (edge.source_id === activeId || edge.target_id === activeId) {
        highlightEdges.add(`${edge.source_id}-${edge.target_id}`);
      }
    }
  }

  // Unique agents for legend
  const agents = [...new Set(graph.nodes.map((n) => n.agent))];

  return (
    <div className="space-y-4">
      {/* Graph */}
      <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
        <div className="px-4 py-2 border-b border-[var(--border)] flex items-center justify-between">
          <span className="text-xs font-theme-data text-[var(--acid-green)]">
            {'>'} ARGUMENT GRAPH
          </span>
          <span className="text-xs font-theme-data text-[var(--text-muted)]">
            {graph.nodes.length} nodes / {graph.edges.length} edges
          </span>
        </div>

        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full"
          style={{ maxHeight: '500px', background: 'var(--bg)' }}
        >
          <defs>
            {Object.entries(EDGE_COLORS).map(([rel, color]) => (
              <marker
                key={rel}
                id={`arrow-${rel}`}
                markerWidth="8"
                markerHeight="6"
                refX="8"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L8,3 L0,6 Z" fill={color} opacity={0.7} />
              </marker>
            ))}
          </defs>

          {/* Edges */}
          {graph.edges.map((edge, i) => {
            const source = nodeMap.get(edge.source_id);
            const target = nodeMap.get(edge.target_id);
            if (!source || !target) return null;

            const edgeKey = `${edge.source_id}-${edge.target_id}`;
            const isHighlighted = highlightEdges.has(edgeKey);
            const opacity = activeId ? (isHighlighted ? 0.9 : 0.15) : 0.5;

            return (
              <line
                key={i}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke={EDGE_COLORS[edge.relation] || '#64748b'}
                strokeWidth={isHighlighted ? 2 : 1}
                opacity={opacity}
                markerEnd={`url(#arrow-${edge.relation})`}
              />
            );
          })}

          {/* Nodes */}
          {layoutNodes.map((node) => {
            const isActive = activeId === node.id;
            const isConnected = activeId
              ? graph.edges.some(
                  (e) =>
                    (e.source_id === activeId && e.target_id === node.id) ||
                    (e.target_id === activeId && e.source_id === node.id),
                )
              : false;
            const dimmed = activeId && !isActive && !isConnected;

            const color = NODE_COLORS[node.data.node_type] || '#94a3b8';
            const radius = node.data.node_type === 'consensus' ? 14 : 10;

            return (
              <g
                key={node.id}
                transform={`translate(${node.x},${node.y})`}
                onClick={() => handleNodeClick(node.data)}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ cursor: 'pointer' }}
                opacity={dimmed ? 0.25 : 1}
              >
                <circle
                  r={radius}
                  fill={color}
                  fillOpacity={0.2}
                  stroke={color}
                  strokeWidth={isActive ? 2.5 : 1.5}
                />
                <text
                  y={-radius - 4}
                  textAnchor="middle"
                  className="text-[9px]"
                  fill="var(--text-muted)"
                  fontFamily="monospace"
                >
                  {node.data.agent.slice(0, 12)}
                </text>
                <text
                  y={3}
                  textAnchor="middle"
                  className="text-[8px]"
                  fill={color}
                  fontFamily="monospace"
                  fontWeight="bold"
                >
                  {node.data.node_type.charAt(0).toUpperCase()}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 px-1">
        <div className="flex flex-wrap gap-2">
          {Object.entries(NODE_COLORS).map(([type, color]) => (
            <span
              key={type}
              className="flex items-center gap-1 text-[10px] font-theme-data text-[var(--text-muted)]"
            >
              <span
                className="inline-block w-2.5 h-2.5 rounded-full border"
                style={{ borderColor: color, backgroundColor: `${color}33` }}
              />
              {type}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(EDGE_COLORS).map(([rel, color]) => (
            <span
              key={rel}
              className="flex items-center gap-1 text-[10px] font-theme-data text-[var(--text-muted)]"
            >
              <span className="inline-block w-3 h-0.5" style={{ backgroundColor: color }} />
              {rel}
            </span>
          ))}
        </div>
      </div>

      {/* Agents */}
      <div className="flex flex-wrap gap-1.5 px-1">
        {agents.map((agent) => (
          <span
            key={agent}
            className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/20"
          >
            {agent}
          </span>
        ))}
      </div>

      {/* Selected node detail panel */}
      {selectedNode && (
        <div className="bg-[var(--surface)] border border-[var(--acid-green)]/40 p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span
                className="px-1.5 py-0.5 text-[10px] font-theme-data border"
                style={{
                  color: NODE_COLORS[selectedNode.node_type],
                  borderColor: `${NODE_COLORS[selectedNode.node_type]}66`,
                  backgroundColor: `${NODE_COLORS[selectedNode.node_type]}1a`,
                }}
              >
                {selectedNode.node_type.toUpperCase()}
              </span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">
                {selectedNode.agent}
              </span>
              <span className="text-xs font-theme-data text-[var(--text-muted)]">
                Round {selectedNode.round_num}
              </span>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              [CLOSE]
            </button>
          </div>
          <p className="text-sm font-theme-data text-[var(--text)] whitespace-pre-wrap">
            {selectedNode.summary}
          </p>
        </div>
      )}
    </div>
  );
}
