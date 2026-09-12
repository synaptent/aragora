'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import * as d3Force from 'd3-force';

// ============================================================================
// Types - Maps to aragora/visualization/mapper.py
// ============================================================================

export type NodeType =
  'proposal' | 'critique' | 'evidence' | 'concession' | 'rebuttal' | 'vote' | 'consensus';

export type EdgeRelation = 'supports' | 'refutes' | 'modifies' | 'responds_to' | 'concedes_to';

export interface ArgumentNode {
  id: string;
  agent: string;
  node_type: NodeType;
  summary: string;
  round_num: number;
  timestamp: number;
  full_content?: string;
  metadata?: Record<string, unknown>;
}

export interface ArgumentEdge {
  source_id: string;
  target_id: string;
  relation: EdgeRelation;
  weight: number;
  metadata?: Record<string, unknown>;
}

export interface GraphData {
  debate_id: string;
  topic: string;
  nodes: ArgumentNode[];
  edges: ArgumentEdge[];
  metadata?: { node_count: number; edge_count: number; exported_at: number };
}

interface SimNode extends d3Force.SimulationNodeDatum {
  id: string;
  node: ArgumentNode;
  x?: number;
  y?: number;
}

interface SimLink extends d3Force.SimulationLinkDatum<SimNode> {
  edge: ArgumentEdge;
}

// ============================================================================
// Styling
// ============================================================================

const NODE_COLORS: Record<NodeType, { fill: string; stroke: string }> = {
  proposal: { fill: '#4CAF50', stroke: '#2E7D32' },
  critique: { fill: '#FF5722', stroke: '#D84315' },
  evidence: { fill: '#9C27B0', stroke: '#6A1B9A' },
  concession: { fill: '#FF9800', stroke: '#E65100' },
  rebuttal: { fill: '#F44336', stroke: '#C62828' },
  vote: { fill: '#607D8B', stroke: '#37474F' },
  consensus: { fill: '#2196F3', stroke: '#1565C0' },
};

const EDGE_COLORS: Record<EdgeRelation, string> = {
  supports: '#4CAF50',
  refutes: '#F44336',
  modifies: '#FF9800',
  responds_to: '#9E9E9E',
  concedes_to: '#FFC107',
};

// ============================================================================
// Component
// ============================================================================

interface ArgumentMapProps {
  data: GraphData;
  width?: number;
  height?: number;
  onNodeClick?: (node: ArgumentNode) => void;
  selectedNodeId?: string | null;
}

export function ArgumentMap({
  data,
  width = 800,
  height = 600,
  onNodeClick,
  selectedNodeId,
}: ArgumentMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simLinks, setSimLinks] = useState<SimLink[]>([]);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });

  // Initialize force simulation
  useEffect(() => {
    if (!data.nodes.length) return;

    // Create node map
    const nodeMap = new Map(data.nodes.map((n) => [n.id, n]));

    // Create simulation nodes
    const nodes: SimNode[] = data.nodes.map((node) => ({
      id: node.id,
      node,
      x: width / 2 + (Math.random() - 0.5) * 200,
      y: node.round_num * 100 + 50,
    }));

    // Create simulation links
    const links: SimLink[] = data.edges
      .filter((e) => nodeMap.has(e.source_id) && nodeMap.has(e.target_id))
      .map((edge) => ({ source: edge.source_id, target: edge.target_id, edge }));

    // Create force simulation
    const simulation = d3Force
      .forceSimulation<SimNode, SimLink>(nodes)
      .force(
        'link',
        d3Force
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance(120)
          .strength(0.5),
      )
      .force('charge', d3Force.forceManyBody<SimNode>().strength(-400).distanceMax(500))
      .force('collide', d3Force.forceCollide<SimNode>(60).strength(0.7))
      .force('x', d3Force.forceX<SimNode>(width / 2).strength(0.03))
      .force('y', d3Force.forceY<SimNode>((d) => d.node.round_num * 100 + 80).strength(0.2));

    // Run simulation
    simulation.tick(200);
    simulation.stop();

    setSimNodes([...nodes]);
    setSimLinks([...links]);

    return () => {
      simulation.stop();
    };
  }, [data, width, height]);

  // Handle zoom/pan with wheel
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform((t) => ({ ...t, k: Math.max(0.3, Math.min(3, t.k * delta)) }));
  }, []);

  // Handle drag for panning
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.target === svgRef.current) {
      setIsDragging(true);
      setDragStart({ x: e.clientX, y: e.clientY });
    }
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging) return;
      const dx = e.clientX - dragStart.x;
      const dy = e.clientY - dragStart.y;
      setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
      setDragStart({ x: e.clientX, y: e.clientY });
    },
    [isDragging, dragStart],
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // Get node position
  const getNodePos = (nodeId: string) => {
    const node = simNodes.find((n) => n.id === nodeId);
    return node ? { x: node.x || 0, y: node.y || 0 } : { x: 0, y: 0 };
  };

  if (!data.nodes.length) {
    return (
      <div
        className="flex items-center justify-center border border-[var(--accent)]/20 bg-surface/30"
        style={{ width, height }}
      >
        <div className="text-center text-text-muted">
          <p className="text-sm font-theme-data">No argument graph data</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative border border-[var(--accent)]/30 bg-bg overflow-hidden"
      style={{ width, height }}
    >
      {/* Legend */}
      <div className="absolute top-2 left-2 z-10 bg-surface/90 border border-[var(--accent)]/20 p-2 text-xs font-theme-data">
        <div className="text-[var(--acid-cyan)] mb-2">Node Types</div>
        <div className="grid grid-cols-2 gap-1">
          {(Object.keys(NODE_COLORS) as NodeType[]).map((type) => (
            <div key={type} className="flex items-center gap-1">
              <div
                className="w-3 h-3 rounded-sm"
                style={{ backgroundColor: NODE_COLORS[type].fill }}
              />
              <span className="text-text-muted capitalize">{type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <button
          onClick={() => setTransform((t) => ({ ...t, k: Math.min(3, t.k * 1.2) }))}
          className="w-8 h-8 bg-surface/90 border border-[var(--accent)]/20 text-[var(--accent)] hover:bg-surface"
        >
          +
        </button>
        <button
          onClick={() => setTransform((t) => ({ ...t, k: Math.max(0.3, t.k * 0.8) }))}
          className="w-8 h-8 bg-surface/90 border border-[var(--accent)]/20 text-[var(--accent)] hover:bg-surface"
        >
          -
        </button>
        <button
          onClick={() => setTransform({ x: 0, y: 0, k: 1 })}
          className="w-8 h-8 bg-surface/90 border border-[var(--accent)]/20 text-[var(--accent)] hover:bg-surface text-xs"
        >
          R
        </button>
      </div>

      {/* SVG Canvas */}
      <svg
        ref={svgRef}
        width={width}
        height={height}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {/* Edges */}
          {simLinks.map((link, i) => {
            const source =
              typeof link.source === 'object' ? link.source : getNodePos(link.source as string);
            const target =
              typeof link.target === 'object' ? link.target : getNodePos(link.target as string);
            const color = EDGE_COLORS[link.edge.relation];

            return (
              <g key={`edge-${i}`}>
                {/* Edge line */}
                <line
                  x1={source.x || 0}
                  y1={source.y || 0}
                  x2={target.x || 0}
                  y2={target.y || 0}
                  stroke={color}
                  strokeWidth={2}
                  strokeOpacity={0.6}
                  markerEnd={`url(#arrow-${link.edge.relation})`}
                />
              </g>
            );
          })}

          {/* Nodes */}
          {simNodes.map((simNode) => {
            const { node } = simNode;
            const colors = NODE_COLORS[node.node_type];
            const isSelected = selectedNodeId === node.id;
            const isHovered = hoveredNode === node.id;

            return (
              <g
                key={node.id}
                transform={`translate(${simNode.x || 0},${simNode.y || 0})`}
                onClick={() => onNodeClick?.(node)}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ cursor: 'pointer' }}
              >
                {/* Node circle */}
                <circle
                  r={isSelected ? 28 : 24}
                  fill={colors.fill}
                  stroke={isSelected ? '#00ff00' : colors.stroke}
                  strokeWidth={isSelected ? 3 : 2}
                  opacity={isHovered ? 1 : 0.9}
                />

                {/* Agent label */}
                <text
                  textAnchor="middle"
                  dy="-0.1em"
                  fill="white"
                  fontSize={10}
                  fontFamily="monospace"
                  fontWeight="bold"
                >
                  {node.agent.slice(0, 6)}
                </text>

                {/* Round number */}
                <text
                  textAnchor="middle"
                  dy="1.1em"
                  fill="rgba(255,255,255,0.7)"
                  fontSize={8}
                  fontFamily="monospace"
                >
                  R{node.round_num}
                </text>
              </g>
            );
          })}
        </g>

        {/* Arrow markers for edges */}
        <defs>
          {(Object.keys(EDGE_COLORS) as EdgeRelation[]).map((rel) => (
            <marker
              key={rel}
              id={`arrow-${rel}`}
              viewBox="0 0 10 10"
              refX={35}
              refY={5}
              markerWidth={5}
              markerHeight={5}
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_COLORS[rel]} />
            </marker>
          ))}
        </defs>
      </svg>

      {/* Tooltip */}
      {hoveredNode && (
        <div className="absolute bottom-2 left-2 right-2 z-10 bg-surface/95 border border-[var(--accent)]/30 p-3">
          {(() => {
            const node = data.nodes.find((n) => n.id === hoveredNode);
            if (!node) return null;
            return (
              <div className="text-xs font-theme-data">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="px-2 py-0.5 rounded text-white"
                    style={{ backgroundColor: NODE_COLORS[node.node_type].fill }}
                  >
                    {node.node_type.toUpperCase()}
                  </span>
                  <span className="text-[var(--accent)] font-bold">{node.agent}</span>
                  <span className="text-text-muted">Round {node.round_num}</span>
                </div>
                <p className="text-text truncate">{node.summary}</p>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

export default ArgumentMap;
