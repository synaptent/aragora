'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import * as d3Force from 'd3-force';
import type { GraphDebate, SimulationNode, SimulationLink, NodePosition } from './types';
import { createForceSimulation, getEdgeColor } from './utils';
import { GraphNode } from './GraphNode';

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

export default GraphVisualization;
