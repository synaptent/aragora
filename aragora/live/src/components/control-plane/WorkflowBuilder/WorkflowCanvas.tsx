'use client';

import { useEffect, useRef, useCallback, useMemo } from 'react';

// Extend SVG element to include D3 zoom state
interface SVGElementWithZoom extends SVGSVGElement {
  __zoom?: d3Zoom.ZoomBehavior<SVGSVGElement, unknown>;
}
import * as d3Selection from 'd3-selection';
import * as d3Zoom from 'd3-zoom';
import * as d3Drag from 'd3-drag';
import { useWorkflowBuilderStore, type StepType } from '@/store/workflowBuilderStore';

export interface WorkflowCanvasProps {
  /** Width of the canvas */
  width?: number;
  /** Height of the canvas */
  height?: number;
  /** Grid size for snapping */
  gridSize?: number;
  /** Show grid */
  showGrid?: boolean;
}

// Node styling
const stepTypeColors: Record<StepType, string> = {
  agent: '#39ff14', // acid-green
  debate: '#60a5fa', // blue
  quick_debate: '#f472b6', // pink
  parallel: '#a855f7', // purple
  conditional: '#fbbf24', // yellow
  loop: '#f97316', // orange
  human_checkpoint: '#ec4899', // pink
  memory_read: '#00ffff', // cyan
  memory_write: '#00ffff', // cyan
  task: '#6b7280', // gray
};

const stepTypeIcons: Record<StepType, string> = {
  agent: '🤖',
  debate: '💬',
  quick_debate: '⚡',
  parallel: '⏸',
  conditional: '❓',
  loop: '🔄',
  human_checkpoint: '👤',
  memory_read: '📖',
  memory_write: '📝',
  task: '📋',
};

/**
 * Canvas component for visual workflow editing using D3.
 */
export function WorkflowCanvas({
  width = 1200,
  height = 800,
  gridSize = 20,
  showGrid = true,
}: WorkflowCanvasProps) {
  const svgRef = useRef<SVGElementWithZoom>(null);
  const containerRef = useRef<SVGGElement | null>(null);

  const {
    currentWorkflow,
    canvas,
    configPanel,
    addNode,
    updateNode,
    deleteNode,
    deleteEdge,
    selectNodes,
    selectEdges,
    clearSelection,
    openConfigPanel,
    setZoom,
    setPan,
    setDragging,
  } = useWorkflowBuilderStore();

  const { zoom, panX, panY, selectedNodeIds, selectedEdgeIds } = canvas;
  const steps = useMemo(() => currentWorkflow?.steps || [], [currentWorkflow?.steps]);
  const transitions = useMemo(
    () => currentWorkflow?.transitions || [],
    [currentWorkflow?.transitions],
  );

  // Snap position to grid
  const snapToGrid = useCallback(
    (pos: number) => Math.round(pos / gridSize) * gridSize,
    [gridSize],
  );

  // Initialize D3 visualization
  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3Selection.select(svgRef.current);

    // Clear existing content
    svg.selectAll('*').remove();

    // Create defs for patterns and markers
    const defs = svg.append('defs');

    // Grid pattern
    if (showGrid) {
      const pattern = defs
        .append('pattern')
        .attr('id', 'grid')
        .attr('width', gridSize)
        .attr('height', gridSize)
        .attr('patternUnits', 'userSpaceOnUse');

      pattern
        .append('path')
        .attr('d', `M ${gridSize} 0 L 0 0 0 ${gridSize}`)
        .attr('fill', 'none')
        .attr('stroke', 'rgba(255,255,255,0.05)')
        .attr('stroke-width', 0.5);
    }

    // Arrow marker for edges
    defs
      .append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 10)
      .attr('refY', 0)
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#6b7280');

    // Selected arrow marker
    defs
      .append('marker')
      .attr('id', 'arrow-selected')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 10)
      .attr('refY', 0)
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#39ff14');

    // Background with grid
    svg
      .append('rect')
      .attr('width', width)
      .attr('height', height)
      .attr('fill', showGrid ? 'url(#grid)' : '#0a0a0a');

    // Container for zoom/pan
    const container = svg.append('g').attr('class', 'canvas-container');
    containerRef.current = container.node();

    // Zoom behavior
    const zoomBehavior = d3Zoom
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.25, 2])
      .on('zoom', (event) => {
        container.attr('transform', event.transform);
        setZoom(event.transform.k);
        setPan(event.transform.x, event.transform.y);
      });

    svg.call(zoomBehavior);

    // Click on background to deselect
    svg.on('click', (event) => {
      if (event.target === svgRef.current || event.target.classList.contains('canvas-bg')) {
        clearSelection();
      }
    });

    // Store zoom behavior for external access
    if (svgRef.current) {
      svgRef.current.__zoom = zoomBehavior;
    }
  }, [width, height, gridSize, showGrid, setZoom, setPan, clearSelection]);

  // Update nodes and edges
  useEffect(() => {
    if (!containerRef.current) return;

    const container = d3Selection.select(containerRef.current);

    // Clear existing elements
    container.selectAll('.edges').remove();
    container.selectAll('.nodes').remove();

    // Create edges group
    const edgesGroup = container.append('g').attr('class', 'edges');

    // Draw edges
    transitions.forEach((transition) => {
      const sourceStep = steps.find((s) => s.id === transition.from_step);
      const targetStep = steps.find((s) => s.id === transition.to_step);

      if (!sourceStep?.position || !targetStep?.position) return;

      const isSelected = selectedEdgeIds.has(transition.id);

      // Calculate edge path (from right side of source to left side of target)
      const sourceX = sourceStep.position.x + 120; // Node width is 120
      const sourceY = sourceStep.position.y + 40; // Node height/2
      const targetX = targetStep.position.x;
      const targetY = targetStep.position.y + 40;

      // Bezier curve control points
      const dx = targetX - sourceX;
      const controlOffset = Math.min(Math.abs(dx) * 0.5, 100);

      const path = `M ${sourceX} ${sourceY}
                    C ${sourceX + controlOffset} ${sourceY},
                      ${targetX - controlOffset} ${targetY},
                      ${targetX} ${targetY}`;

      edgesGroup
        .append('path')
        .attr('d', path)
        .attr('fill', 'none')
        .attr('stroke', isSelected ? '#39ff14' : '#6b7280')
        .attr('stroke-width', isSelected ? 2 : 1.5)
        .attr('marker-end', isSelected ? 'url(#arrow-selected)' : 'url(#arrow)')
        .attr('class', 'edge')
        .attr('cursor', 'pointer')
        .on('click', (event) => {
          event.stopPropagation();
          selectEdges([transition.id]);
        })
        .on('dblclick', (event) => {
          event.stopPropagation();
          if (confirm('Delete this connection?')) {
            deleteEdge(transition.id);
          }
        });

      // Add condition label if present
      if (transition.condition || transition.label) {
        const midX = (sourceX + targetX) / 2;
        const midY = (sourceY + targetY) / 2 - 10;

        edgesGroup
          .append('text')
          .attr('x', midX)
          .attr('y', midY)
          .attr('text-anchor', 'middle')
          .attr('fill', '#6b7280')
          .attr('font-size', '10px')
          .attr('font-family', 'monospace')
          .text(transition.label || transition.condition || '');
      }
    });

    // Create nodes group
    const nodesGroup = container.append('g').attr('class', 'nodes');

    // Draw nodes
    steps.forEach((step) => {
      if (!step.position) return;

      const isSelected = selectedNodeIds.has(step.id);
      const color = stepTypeColors[step.step_type] || '#6b7280';

      const nodeGroup = nodesGroup
        .append('g')
        .attr('class', 'node')
        .attr('transform', `translate(${step.position.x}, ${step.position.y})`)
        .attr('cursor', 'move');

      // Node background
      nodeGroup
        .append('rect')
        .attr('width', 120)
        .attr('height', 80)
        .attr('rx', 8)
        .attr('fill', '#0d0d0d')
        .attr('stroke', isSelected ? '#39ff14' : color)
        .attr('stroke-width', isSelected ? 2 : 1);

      // Type indicator bar
      nodeGroup
        .append('rect')
        .attr('width', 120)
        .attr('height', 4)
        .attr('rx', 2)
        .attr('fill', color);

      // Icon
      nodeGroup
        .append('text')
        .attr('x', 10)
        .attr('y', 30)
        .attr('font-size', '16px')
        .text(stepTypeIcons[step.step_type] || '📦');

      // Name
      nodeGroup
        .append('text')
        .attr('x', 35)
        .attr('y', 32)
        .attr('fill', '#e0e0e0')
        .attr('font-size', '11px')
        .attr('font-family', 'monospace')
        .text(step.name.length > 12 ? step.name.slice(0, 12) + '...' : step.name);

      // Type label
      nodeGroup
        .append('text')
        .attr('x', 10)
        .attr('y', 55)
        .attr('fill', '#6b7280')
        .attr('font-size', '9px')
        .attr('font-family', 'monospace')
        .text(step.step_type);

      // Connection handles
      // Output handle (right side)
      nodeGroup
        .append('circle')
        .attr('cx', 120)
        .attr('cy', 40)
        .attr('r', 5)
        .attr('fill', '#0d0d0d')
        .attr('stroke', color)
        .attr('stroke-width', 1)
        .attr('class', 'output-handle')
        .attr('cursor', 'crosshair');

      // Input handle (left side)
      nodeGroup
        .append('circle')
        .attr('cx', 0)
        .attr('cy', 40)
        .attr('r', 5)
        .attr('fill', '#0d0d0d')
        .attr('stroke', color)
        .attr('stroke-width', 1)
        .attr('class', 'input-handle');

      // Click handler
      nodeGroup.on('click', (event) => {
        event.stopPropagation();
        selectNodes([step.id]);
      });

      // Double-click to edit
      nodeGroup.on('dblclick', (event) => {
        event.stopPropagation();
        openConfigPanel(step.id);
      });

      // Drag behavior
      const drag = d3Drag
        .drag<SVGGElement, unknown>()
        .on('start', () => {
          setDragging(true, step.id);
        })
        .on('drag', (event) => {
          const newX = snapToGrid(event.x);
          const newY = snapToGrid(event.y);
          nodeGroup.attr('transform', `translate(${newX}, ${newY})`);
        })
        .on('end', (event) => {
          const newX = snapToGrid(event.x);
          const newY = snapToGrid(event.y);
          updateNode(step.id, { position: { x: newX, y: newY } });
          setDragging(false);
        });

      nodeGroup.call(drag);
    });
  }, [
    steps,
    transitions,
    selectedNodeIds,
    selectedEdgeIds,
    snapToGrid,
    selectNodes,
    selectEdges,
    deleteEdge,
    openConfigPanel,
    updateNode,
    setDragging,
  ]);

  // Handle drop from palette
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();

      const type = e.dataTransfer.getData('application/workflow-node') as StepType;
      if (!type) return;

      // Get drop position relative to canvas
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;

      const x = snapToGrid((e.clientX - rect.left - panX) / zoom);
      const y = snapToGrid((e.clientY - rect.top - panY) / zoom);

      addNode(type, { x, y });
    },
    [addNode, snapToGrid, zoom, panX, panY],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }, []);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Delete selected nodes/edges
      if ((e.key === 'Delete' || e.key === 'Backspace') && !configPanel.isOpen) {
        if (selectedNodeIds.size > 0) {
          selectedNodeIds.forEach((id) => deleteNode(id));
        }
        if (selectedEdgeIds.size > 0) {
          selectedEdgeIds.forEach((id) => deleteEdge(id));
        }
      }

      // Escape to deselect
      if (e.key === 'Escape') {
        clearSelection();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    selectedNodeIds,
    selectedEdgeIds,
    configPanel.isOpen,
    deleteNode,
    deleteEdge,
    clearSelection,
  ]);

  return (
    <div
      className="relative overflow-hidden bg-bg border border-border rounded-lg"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="cursor-grab active:cursor-grabbing"
      />

      {/* Zoom controls */}
      <div className="absolute bottom-4 right-4 flex items-center gap-2 bg-surface/80 p-2 rounded border border-border">
        <button
          onClick={() => {
            const newZoom = Math.min(zoom + 0.1, 2);
            setZoom(newZoom);
          }}
          className="w-8 h-8 text-sm bg-bg border border-border rounded hover:border-text-muted"
        >
          +
        </button>
        <span className="text-xs font-theme-data text-text-muted w-12 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => {
            const newZoom = Math.max(zoom - 0.1, 0.25);
            setZoom(newZoom);
          }}
          className="w-8 h-8 text-sm bg-bg border border-border rounded hover:border-text-muted"
        >
          -
        </button>
        <button
          onClick={() => {
            setZoom(1);
            setPan(0, 0);
          }}
          className="w-8 h-8 text-xs bg-bg border border-border rounded hover:border-text-muted"
          title="Reset view"
        >
          ⊙
        </button>
      </div>

      {/* Empty state */}
      {steps.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center">
            <div className="text-6xl mb-4 opacity-50">📝</div>
            <p className="text-text-muted">Drag nodes from the palette to start building</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default WorkflowCanvas;
