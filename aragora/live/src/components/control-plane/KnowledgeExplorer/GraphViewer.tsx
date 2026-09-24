'use client';

import { useEffect, useRef, useMemo } from 'react';
import * as d3Force from 'd3-force';
import * as d3Selection from 'd3-selection';
import * as d3Zoom from 'd3-zoom';
import * as d3Drag from 'd3-drag';
import type {
  GraphNode,
  GraphEdge,
  NodeType,
  RelationshipType,
} from '@/store/knowledgeExplorerStore';

export interface GraphViewerProps {
  /** Graph nodes */
  nodes: GraphNode[];
  /** Graph edges */
  edges: GraphEdge[];
  /** Currently selected node ID */
  selectedNodeId?: string | null;
  /** Hovered node ID */
  hoveredNodeId?: string | null;
  /** Callback when a node is clicked */
  onNodeClick?: (node: GraphNode) => void;
  /** Callback when a node is hovered */
  onNodeHover?: (nodeId: string | null) => void;
  /** Callback when node position changes (drag) */
  onNodePositionChange?: (nodeId: string, x: number, y: number) => void;
  /** Width of the viewer */
  width?: number;
  /** Height of the viewer */
  height?: number;
  /** Loading state */
  loading?: boolean;
  /** Show node labels */
  showLabels?: boolean;
}

// Color schemes
const nodeTypeColors: Record<NodeType, string> = {
  fact: '#39ff14', // acid-green
  claim: '#60a5fa', // blue
  memory: '#a855f7', // purple
  evidence: '#fbbf24', // yellow
  consensus: '#00ffff', // acid-cyan
  entity: '#f97316', // orange
};

const edgeTypeColors: Record<RelationshipType, string> = {
  supports: '#39ff14',
  contradicts: '#ef4444',
  derived_from: '#60a5fa',
  related_to: '#6b7280',
  supersedes: '#a855f7',
};

// D3 simulation modifies edges to reference node objects
interface SimulatedGraphEdge {
  id: string;
  source: GraphNode;
  target: GraphNode;
  type: RelationshipType;
  strength: number;
}

/**
 * D3-based force-directed graph viewer for knowledge relationships.
 */
export function GraphViewer({
  nodes,
  edges,
  selectedNodeId,
  hoveredNodeId,
  onNodeClick,
  onNodeHover,
  onNodePositionChange,
  width = 800,
  height = 500,
  loading = false,
  showLabels = true,
}: GraphViewerProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3Force.Simulation<GraphNode, GraphEdge> | null>(null);

  // Build link data with proper source/target
  const linkData = useMemo(() => {
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));
    return edges
      .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map((e) => ({ ...e, source: e.source, target: e.target }));
  }, [nodes, edges]);

  // Initialize and update D3 visualization
  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3Selection.select(svgRef.current);

    // Clear existing content
    svg.selectAll('*').remove();

    // Create container group for zoom/pan
    const container = svg.append('g').attr('class', 'graph-container');

    // Add zoom behavior
    const zoom = d3Zoom
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        container.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Create arrow markers for directed edges
    const defs = svg.append('defs');

    Object.entries(edgeTypeColors).forEach(([type, color]) => {
      defs
        .append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 20)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', color);
    });

    // Create force simulation
    const simulation = d3Force
      .forceSimulation<GraphNode>(nodes)
      .force(
        'link',
        d3Force
          .forceLink<GraphNode, GraphEdge>(linkData)
          .id((d) => d.id)
          .distance(100),
      )
      .force('charge', d3Force.forceManyBody().strength(-300))
      .force('center', d3Force.forceCenter(width / 2, height / 2))
      .force('collision', d3Force.forceCollide().radius(30));

    simulationRef.current = simulation;

    // Create edge lines
    const links = container
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(linkData)
      .join('line')
      .attr('stroke', (d) => edgeTypeColors[d.type] || '#6b7280')
      .attr('stroke-width', (d) => Math.max(1, d.strength * 3))
      .attr('stroke-opacity', 0.6)
      .attr('marker-end', (d) => `url(#arrow-${d.type})`);

    // Create node groups
    const nodeGroups = container
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'node-group')
      .style('cursor', 'pointer');

    // Add circles to nodes
    nodeGroups
      .append('circle')
      .attr('r', (d) => (d.depth === 0 ? 15 : 10))
      .attr('fill', (d) => nodeTypeColors[d.node_type] || '#6b7280')
      .attr('stroke', (d) =>
        d.id === selectedNodeId
          ? '#fff'
          : d.id === hoveredNodeId
            ? 'rgba(255,255,255,0.5)'
            : 'none',
      )
      .attr('stroke-width', 2)
      .attr('opacity', (d) => (d.id === selectedNodeId || d.id === hoveredNodeId ? 1 : 0.8));

    // Add labels if enabled
    if (showLabels) {
      nodeGroups
        .append('text')
        .text((d) => {
          const maxLen = 20;
          return d.content.length > maxLen ? d.content.slice(0, maxLen) + '...' : d.content;
        })
        .attr('x', 15)
        .attr('y', 4)
        .attr('font-size', '10px')
        .attr('font-family', 'monospace')
        .attr('fill', '#e0e0e0')
        .attr('opacity', 0.8);
    }

    // Add node type indicator
    nodeGroups
      .append('text')
      .text((d) => {
        const icons: Record<NodeType, string> = {
          fact: 'F',
          claim: 'C',
          memory: 'M',
          evidence: 'E',
          consensus: '✓',
          entity: 'N',
        };
        return icons[d.node_type] || '?';
      })
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('font-size', '8px')
      .attr('font-family', 'monospace')
      .attr('fill', '#0a0a0a')
      .attr('font-weight', 'bold');

    // Drag behavior
    const drag = d3Drag
      .drag<SVGGElement, GraphNode>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        // Keep node fixed after drag
        onNodePositionChange?.(d.id, event.x, event.y);
      });

    (
      nodeGroups as unknown as d3Selection.Selection<SVGGElement, GraphNode, SVGGElement, unknown>
    ).call(drag);

    // Click handler
    nodeGroups.on('click', (event, d) => {
      event.stopPropagation();
      onNodeClick?.(d);
    });

    // Hover handlers
    nodeGroups
      .on('mouseenter', (event, d) => {
        onNodeHover?.(d.id);
      })
      .on('mouseleave', () => {
        onNodeHover?.(null);
      });

    // Update positions on each tick
    simulation.on('tick', () => {
      links
        .attr('x1', (d) => (d as unknown as SimulatedGraphEdge).source.x ?? 0)
        .attr('y1', (d) => (d as unknown as SimulatedGraphEdge).source.y ?? 0)
        .attr('x2', (d) => (d as unknown as SimulatedGraphEdge).target.x ?? 0)
        .attr('y2', (d) => (d as unknown as SimulatedGraphEdge).target.y ?? 0);

      nodeGroups.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Cleanup
    return () => {
      simulation.stop();
    };
  }, [
    nodes,
    linkData,
    width,
    height,
    selectedNodeId,
    hoveredNodeId,
    showLabels,
    onNodeClick,
    onNodeHover,
    onNodePositionChange,
  ]);

  // Update visual states when selection changes
  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3Selection.select(svgRef.current);

    svg
      .selectAll<SVGCircleElement, GraphNode>('.node-group circle')
      .attr('stroke', (d) =>
        d.id === selectedNodeId
          ? '#fff'
          : d.id === hoveredNodeId
            ? 'rgba(255,255,255,0.5)'
            : 'none',
      )
      .attr('opacity', (d) => (d.id === selectedNodeId || d.id === hoveredNodeId ? 1 : 0.8));
  }, [selectedNodeId, hoveredNodeId]);

  if (loading) {
    return (
      <div
        className="flex items-center justify-center bg-surface border border-border rounded-lg"
        style={{ width, height }}
      >
        <div className="text-center">
          <div className="animate-spin text-4xl mb-2">⟳</div>
          <p className="text-text-muted text-sm">Loading graph...</p>
        </div>
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center bg-surface border border-border rounded-lg"
        style={{ width, height }}
      >
        <div className="text-center">
          <div className="text-4xl mb-2">🔗</div>
          <p className="text-text-muted text-sm">Select a node to view its relationships</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="bg-surface border border-border rounded-lg"
        style={{ background: 'radial-gradient(circle at center, #0d0d0d 0%, #0a0a0a 100%)' }}
      />

      {/* Legend */}
      <div className="absolute bottom-2 left-2 bg-bg/80 p-2 rounded border border-border text-xs">
        <div className="text-text-muted mb-1">Node Types</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(nodeTypeColors).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-text-muted capitalize">{type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="absolute top-2 right-2 flex gap-1">
        <button
          onClick={() => {
            const svg = d3Selection.select<SVGSVGElement, unknown>(svgRef.current!);
            const zoom = d3Zoom.zoom<SVGSVGElement, unknown>();
            svg.call(zoom.transform, d3Zoom.zoomIdentity);
          }}
          className="px-2 py-1 text-xs bg-surface border border-border rounded hover:border-text-muted transition-colors"
          title="Reset zoom"
        >
          ⊙
        </button>
      </div>
    </div>
  );
}

export default GraphViewer;
