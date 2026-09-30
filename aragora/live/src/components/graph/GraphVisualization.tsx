'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import * as d3Force from 'd3-force';
import type {
  DebateNode,
  GraphDebate,
  SimulationNode,
  SimulationLink,
  NodePosition,
} from './types';
import { getBranchColor, getEdgeColor } from './types';

// Calculate node depths using BFS
function calculateNodeDepths(
  nodes: Record<string, DebateNode>,
  rootId: string | null,
): Map<string, number> {
  const depths = new Map<string, number>();
  if (!rootId || !nodes[rootId]) return depths;

  const visited = new Set<string>();
  const queue: Array<{ id: string; depth: number }> = [{ id: rootId, depth: 0 }];

  while (queue.length > 0) {
    const { id, depth } = queue.shift()!;
    if (visited.has(id)) continue;
    visited.add(id);
    depths.set(id, depth);

    const node = nodes[id];
    if (node) {
      for (const childId of node.child_ids) {
        if (!visited.has(childId)) {
          queue.push({ id: childId, depth: depth + 1 });
        }
      }
    }
  }

  return depths;
}

// Create force simulation for graph layout
function createForceSimulation(
  nodes: Record<string, DebateNode>,
  rootId: string | null,
  width: number,
  height: number,
): {
  nodes: SimulationNode[];
  links: SimulationLink[];
  simulation: d3Force.Simulation<SimulationNode, SimulationLink>;
} {
  const depths = calculateNodeDepths(nodes, rootId);
  const maxDepth = Math.max(...Array.from(depths.values()), 0);
  const levelHeight = height / (maxDepth + 2);

  // Create simulation nodes
  const simNodes: SimulationNode[] = Object.values(nodes).map((node) => ({
    id: node.id,
    node,
    depth: depths.get(node.id) || 0,
    x: width / 2 + (Math.random() - 0.5) * 100,
    y: (depths.get(node.id) || 0) * levelHeight + 60,
  }));

  // Create links from parent-child relationships
  const simLinks: SimulationLink[] = [];
  Object.values(nodes).forEach((node) => {
    node.parent_ids.forEach((parentId) => {
      if (nodes[parentId]) {
        simLinks.push({ source: parentId, target: node.id, branchId: node.branch_id || 'main' });
      }
    });
  });

  // Create D3 force simulation
  const simulation = d3Force
    .forceSimulation<SimulationNode, SimulationLink>(simNodes)
    .force(
      'link',
      d3Force
        .forceLink<SimulationNode, SimulationLink>(simLinks)
        .id((d) => d.id)
        .distance(100)
        .strength(0.8),
    )
    .force('charge', d3Force.forceManyBody<SimulationNode>().strength(-300).distanceMax(400))
    .force('collide', d3Force.forceCollide<SimulationNode>().radius(50).strength(0.7))
    .force('x', d3Force.forceX<SimulationNode>(width / 2).strength(0.05))
    .force('y', d3Force.forceY<SimulationNode>((d) => d.depth * levelHeight + 60).strength(0.3))
    .alphaDecay(0.02)
    .velocityDecay(0.4);

  // Run simulation for initial layout
  simulation.tick(150);
  simulation.stop();

  return { nodes: simNodes, links: simLinks, simulation };
}

function NodeTypeIcon({ type }: { type: string }) {
  const icons: Record<string, string> = {
    root: 'O',
    proposal: 'P',
    critique: 'C',
    synthesis: 'S',
    branch_point: '/',
    merge_point: 'M',
    counterfactual: '?',
    conclusion: 'X',
  };
  return <span className="font-bold">{icons[type] || '.'}</span>;
}

interface GraphNodeProps {
  position: NodePosition;
  isSelected: boolean;
  onClick: () => void;
}

function GraphNode({ position, isSelected, onClick }: GraphNodeProps) {
  const { node, x, y } = position;
  const colors = getAgentColors(node.agent_id);
  const branchColor = getBranchColor(node.branch_id || 'main');

  return (
    <g transform={`translate(${x}, ${y})`} onClick={onClick} className="cursor-pointer">
      {/* Node circle */}
      <circle
        r={isSelected ? 28 : 24}
        className={`${isSelected ? 'fill-acid-green/30' : 'fill-surface'} stroke-2 transition-all duration-200`}
        style={{
          stroke: isSelected ? '#00ff00' : colors.text.replace('text-', '#'),
          filter: isSelected ? 'drop-shadow(0 0 8px #00ff00)' : undefined,
        }}
      />

      {/* Node type icon */}
      <text
        textAnchor="middle"
        dominantBaseline="central"
        className={`text-xs font-theme-data ${branchColor}`}
        style={{ pointerEvents: 'none' }}
      >
        <NodeTypeIcon type={node.node_type} />
      </text>

      {/* Confidence indicator */}
      {node.confidence > 0 && (
        <text y={35} textAnchor="middle" className="text-[10px] font-theme-data fill-text-muted">
          {(node.confidence * 100).toFixed(0)}%
        </text>
      )}

      {/* Agent label */}
      <text y={-35} textAnchor="middle" className={`text-[10px] font-theme-data ${colors.text}`}>
        {node.agent_id.slice(0, 8)}
      </text>
    </g>
  );
}

export interface NodeDetailPanelProps {
  node: DebateNode;
  onClose: () => void;
}

export function NodeDetailPanel({ node, onClose }: NodeDetailPanelProps) {
  const colors = getAgentColors(node.agent_id);

  return (
    <div className="absolute top-4 right-4 w-96 bg-surface border border-[var(--accent)]/30 shadow-lg z-10">
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 ${colors.bg} ${colors.text} text-xs font-theme-data`}>
            {node.agent_id}
          </span>
          <span className="text-xs font-theme-data text-text-muted uppercase">
            {node.node_type.replace('_', ' ')}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-[var(--accent)] text-xs font-theme-data"
          aria-label="Close node details"
        >
          [X]
        </button>
      </div>

      <div className="p-4 space-y-3 max-h-[60vh] overflow-y-auto">
        {/* Content */}
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">CONTENT</div>
          <div className="text-sm font-theme-data text-text whitespace-pre-wrap">
            {node.content.length > 500 ? node.content.slice(0, 500) + '...' : node.content}
          </div>
        </div>

        {/* Claims */}
        {node.claims.length > 0 && (
          <div>
            <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-1">
              CLAIMS ({node.claims.length})
            </div>
            <ul className="space-y-1">
              {node.claims.slice(0, 5).map((claim, i) => (
                <li
                  key={i}
                  className="text-xs font-theme-data text-text-muted pl-2 border-l border-[var(--acid-cyan)]/30"
                >
                  {claim.slice(0, 100)}
                  {claim.length > 100 ? '...' : ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Metadata */}
        <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
          <div>
            <span className="text-text-muted">Branch: </span>
            <span className={getBranchColor(node.branch_id || 'main')}>
              {node.branch_id || 'main'}
            </span>
          </div>
          <div>
            <span className="text-text-muted">Confidence: </span>
            <span className="text-[var(--accent)]">{(node.confidence * 100).toFixed(0)}%</span>
          </div>
          <div>
            <span className="text-text-muted">Parents: </span>
            <span className="text-text">{node.parent_ids.length}</span>
          </div>
          <div>
            <span className="text-text-muted">Children: </span>
            <span className="text-text">{node.child_ids.length}</span>
          </div>
        </div>

        {/* Hash */}
        <div className="text-[10px] font-theme-data text-text-muted/50 pt-2 border-t border-border">
          Hash: {node.hash}
        </div>
      </div>
    </div>
  );
}

export interface GraphVisualizationProps {
  graph: GraphDebate['graph'];
  selectedNodeId: string | null;
  onNodeSelect: (nodeId: string | null) => void;
  highlightedBranch: string | null;
  onBranchHover: (branchId: string | null) => void;
}

export function GraphVisualization({
  graph,
  selectedNodeId,
  onNodeSelect,
  highlightedBranch,
  onBranchHover,
}: GraphVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [positions, setPositions] = useState<NodePosition[]>([]);
  const [isSimulating, setIsSimulating] = useState(false);
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const simulationRef = useRef<d3Force.Simulation<SimulationNode, SimulationLink> | null>(null);
  const nodesRef = useRef<SimulationNode[]>([]);
  const linksRef = useRef<SimulationLink[]>([]);

  // Initialize force simulation
  useEffect(() => {
    if (!graph.root_id || Object.keys(graph.nodes).length === 0) {
      setPositions([]);
      return;
    }

    const width = 800;
    const height = 600;
    const {
      nodes: simNodes,
      links: simLinks,
      simulation,
    } = createForceSimulation(graph.nodes, graph.root_id, width, height);

    nodesRef.current = simNodes;
    linksRef.current = simLinks;
    simulationRef.current = simulation;

    // Update positions from simulation
    const updatePositions = () => {
      setPositions(
        nodesRef.current.map((simNode) => ({
          x: simNode.x || 400,
          y: simNode.y || 60,
          node: simNode.node,
        })),
      );
    };

    // Initial positions
    updatePositions();

    // Re-run simulation with animation on mount
    setIsSimulating(true);
    simulation.alpha(0.3).restart();

    simulation.on('tick', () => {
      updatePositions();
    });

    simulation.on('end', () => {
      setIsSimulating(false);
    });

    return () => {
      simulation.stop();
    };
  }, [graph.nodes, graph.root_id]);

  // Calculate SVG dimensions
  const minX = positions.length > 0 ? Math.min(...positions.map((p) => p.x)) - 60 : 0;
  const maxX = positions.length > 0 ? Math.max(...positions.map((p) => p.x)) + 60 : 800;
  const maxY = positions.length > 0 ? Math.max(...positions.map((p) => p.y)) + 80 : 400;

  const baseWidth = Math.max(800, maxX - minX);
  const baseHeight = Math.max(400, maxY);

  // Generate edges
  const edges: Array<{ from: NodePosition; to: NodePosition; branchId: string }> = [];
  positions.forEach((toPos) => {
    toPos.node.parent_ids.forEach((parentId) => {
      const fromPos = positions.find((p) => p.node.id === parentId);
      if (fromPos) {
        edges.push({ from: fromPos, to: toPos, branchId: toPos.node.branch_id || 'main' });
      }
    });
  });

  // Zoom controls
  const handleZoomIn = () => setZoom((z) => Math.min(z * 1.2, 3));
  const handleZoomOut = () => setZoom((z) => Math.max(z / 1.2, 0.3));
  const handleResetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  // Reheat simulation
  const handleReheat = useCallback(() => {
    if (simulationRef.current) {
      setIsSimulating(true);
      // Release all fixed positions
      nodesRef.current.forEach((node) => {
        node.fx = null;
        node.fy = null;
      });
      simulationRef.current.alpha(0.5).restart();
    }
  }, []);

  // Pan handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button === 0 && e.shiftKey) {
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    }
  };

  const handleMouseUp = () => {
    setIsPanning(false);
  };

  // Wheel zoom
  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setZoom((z) => Math.max(0.3, Math.min(3, z * delta)));
    }
  };

  // Node drag handlers
  const handleNodeDragStart = useCallback((nodeId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDraggedNode(nodeId);

    if (simulationRef.current) {
      simulationRef.current.alphaTarget(0.3).restart();
    }

    const simNode = nodesRef.current.find((n) => n.id === nodeId);
    if (simNode) {
      simNode.fx = simNode.x;
      simNode.fy = simNode.y;
    }
  }, []);

  const handleNodeDragEnd = useCallback(() => {
    setDraggedNode(null);

    if (simulationRef.current) {
      simulationRef.current.alphaTarget(0);
    }
  }, []);

  // Global mouse move/up for drag
  useEffect(() => {
    if (!draggedNode) return;

    const handleGlobalMouseMove = (e: MouseEvent) => {
      const svg = svgRef.current;
      if (!svg) return;

      const rect = svg.getBoundingClientRect();
      const svgX = (e.clientX - rect.left - pan.x) / zoom + minX;
      const svgY = (e.clientY - rect.top - pan.y) / zoom;

      const simNode = nodesRef.current.find((n) => n.id === draggedNode);
      if (simNode) {
        simNode.fx = svgX;
        simNode.fy = svgY;
      }
    };

    const handleGlobalMouseUp = () => {
      handleNodeDragEnd();
    };

    window.addEventListener('mousemove', handleGlobalMouseMove);
    window.addEventListener('mouseup', handleGlobalMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleGlobalMouseMove);
      window.removeEventListener('mouseup', handleGlobalMouseUp);
    };
  }, [draggedNode, pan.x, pan.y, zoom, minX, handleNodeDragEnd]);

  const isNodeInHighlightedBranch = (branchId: string | null) => {
    if (!highlightedBranch) return true;
    return branchId === highlightedBranch || branchId === null;
  };

  return (
    <div className="relative" ref={containerRef}>
      {/* Zoom controls */}
      <div className="absolute top-2 left-2 z-10 flex gap-1">
        <button
          onClick={handleZoomIn}
          className="w-8 h-8 bg-surface border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/20"
          title="Zoom in"
        >
          +
        </button>
        <button
          onClick={handleZoomOut}
          className="w-8 h-8 bg-surface border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/20"
          title="Zoom out"
        >
          -
        </button>
        <button
          onClick={handleResetView}
          className="px-2 h-8 bg-surface border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data text-xs hover:bg-[var(--accent)]/20"
          title="Reset view"
        >
          RESET
        </button>
        <button
          onClick={handleReheat}
          className={`px-2 h-8 bg-surface border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] font-theme-data text-xs hover:bg-[var(--acid-cyan)]/20 ${
            isSimulating ? 'animate-pulse' : ''
          }`}
          title="Re-run force simulation"
        >
          {isSimulating ? 'SIMULATING...' : 'RELAYOUT'}
        </button>
        <span className="h-8 flex items-center px-2 text-xs font-theme-data text-text-muted">
          {Math.round(zoom * 100)}%
        </span>
      </div>

      {/* Pan hint */}
      <div className="absolute top-2 right-2 z-10 text-xs font-theme-data text-text-muted/50">
        Drag nodes | Shift+drag to pan | Ctrl+scroll to zoom
      </div>

      <svg
        ref={svgRef}
        width="100%"
        height={baseHeight}
        viewBox={`${minX - pan.x / zoom} ${-pan.y / zoom} ${baseWidth / zoom} ${baseHeight / zoom}`}
        className={`bg-bg/50 ${isPanning ? 'cursor-grabbing' : draggedNode ? 'cursor-grabbing' : 'cursor-default'}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#00ff00" fillOpacity="0.5" />
          </marker>
          {/* Highlighted arrowhead */}
          <marker
            id="arrowhead-highlighted"
            markerWidth="12"
            markerHeight="9"
            refX="11"
            refY="4.5"
            orient="auto"
          >
            <polygon points="0 0, 12 4.5, 0 9" fill="#ffffff" fillOpacity="0.8" />
          </marker>
        </defs>

        {/* Edges */}
        {edges.map((edge, i) => {
          const isHighlighted = highlightedBranch === edge.branchId;
          const isDimmed = highlightedBranch && !isHighlighted;

          return (
            <line
              key={i}
              x1={edge.from.x}
              y1={edge.from.y + 24}
              x2={edge.to.x}
              y2={edge.to.y - 24}
              stroke={getEdgeColor(edge.branchId)}
              strokeWidth={isHighlighted ? 3 : 2}
              strokeOpacity={isDimmed ? 0.2 : isHighlighted ? 1 : 0.6}
              markerEnd={isHighlighted ? 'url(#arrowhead-highlighted)' : 'url(#arrowhead)'}
              className="transition-all duration-100"
              onMouseEnter={() => onBranchHover(edge.branchId)}
              onMouseLeave={() => onBranchHover(null)}
            />
          );
        })}

        {/* Nodes */}
        {positions.map((pos) => {
          const nodeInBranch = isNodeInHighlightedBranch(pos.node.branch_id);
          const isDragging = draggedNode === pos.node.id;

          return (
            <g
              key={pos.node.id}
              style={{ opacity: nodeInBranch ? 1 : 0.3, cursor: isDragging ? 'grabbing' : 'grab' }}
              className="transition-opacity duration-200"
              onMouseDown={(e) => handleNodeDragStart(pos.node.id, e)}
            >
              <GraphNode
                position={pos}
                isSelected={selectedNodeId === pos.node.id || isDragging}
                onClick={() => !isDragging && onNodeSelect(pos.node.id)}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
