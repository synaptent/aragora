'use client';

/**
 * Agent Workflow Visualization Component
 *
 * D3-based force-directed graph showing the document audit pipeline:
 * - Agent nodes with real-time status indicators
 * - Document flow arrows between processing stages
 * - Job progress overlays
 * - Interactive node selection and details
 */

import { useEffect, useRef, useMemo, useState } from 'react';
import * as d3 from 'd3-force';
import * as d3Select from 'd3-selection';
import { zoom as d3Zoom } from 'd3-zoom';
import { drag as d3Drag, type D3DragEvent } from 'd3-drag';
import type { AgentState, JobState } from '@/hooks/useControlPlaneWebSocket';

// Node types in the workflow
export type WorkflowNodeType = 'ingest' | 'chunk' | 'scan' | 'verify' | 'report' | 'agent';

export interface WorkflowNode extends d3.SimulationNodeDatum {
  id: string;
  type: WorkflowNodeType;
  label: string;
  status: 'idle' | 'working' | 'error' | 'complete';
  agent?: AgentState;
  progress?: number;
}

export interface WorkflowLink {
  source: string;
  target: string;
  type: 'flow' | 'assigns' | 'produces';
  active?: boolean;
}

// D3 simulation modifies links to reference node objects
interface SimulatedWorkflowLink extends d3.SimulationLinkDatum<WorkflowNode> {
  source: WorkflowNode;
  target: WorkflowNode;
  type: 'flow' | 'assigns' | 'produces';
  active?: boolean;
}

interface AgentWorkflowVisualizationProps {
  agents: AgentState[];
  jobs: JobState[];
  width?: number;
  height?: number;
  onNodeClick?: (node: WorkflowNode) => void;
  onAgentClick?: (agent: AgentState) => void;
}

// Colors for different states
const STATUS_COLORS: Record<string, string> = {
  idle: '#39ff14', // acid-green
  working: '#00ffff', // cyan
  error: '#ff3939', // red
  complete: '#39ff14', // acid-green
  rate_limited: '#ffff39', // yellow
};

const NODE_COLORS: Record<WorkflowNodeType, string> = {
  ingest: '#39ff14',
  chunk: '#00ffff',
  scan: '#ff9900',
  verify: '#ff39ff',
  report: '#39ffff',
  agent: '#666666',
};

const NODE_RADIUS: Record<WorkflowNodeType, number> = {
  ingest: 20,
  chunk: 18,
  scan: 22,
  verify: 20,
  report: 18,
  agent: 16,
};

// Pipeline stage definitions
const PIPELINE_STAGES: { id: string; type: WorkflowNodeType; label: string }[] = [
  { id: 'stage-ingest', type: 'ingest', label: 'INGEST' },
  { id: 'stage-chunk', type: 'chunk', label: 'CHUNK' },
  { id: 'stage-scan', type: 'scan', label: 'SCAN' },
  { id: 'stage-verify', type: 'verify', label: 'VERIFY' },
  { id: 'stage-report', type: 'report', label: 'REPORT' },
];

// Pipeline flow links
const PIPELINE_LINKS: WorkflowLink[] = [
  { source: 'stage-ingest', target: 'stage-chunk', type: 'flow' },
  { source: 'stage-chunk', target: 'stage-scan', type: 'flow' },
  { source: 'stage-scan', target: 'stage-verify', type: 'flow' },
  { source: 'stage-verify', target: 'stage-report', type: 'flow' },
];

export function AgentWorkflowVisualization({
  agents,
  jobs,
  width = 900,
  height = 400,
  onNodeClick,
  onAgentClick,
}: AgentWorkflowVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [selectedNode, setSelectedNode] = useState<WorkflowNode | null>(null);

  // Determine which stages are active based on running jobs
  const activeStages = useMemo(() => {
    const active = new Set<string>();
    jobs.forEach((job) => {
      if (job.status === 'running') {
        const phase = job.phase?.toLowerCase() || '';
        if (phase.includes('ingest') || phase.includes('upload')) active.add('stage-ingest');
        if (phase.includes('chunk') || phase.includes('process')) active.add('stage-chunk');
        if (phase.includes('scan') || phase.includes('audit')) active.add('stage-scan');
        if (phase.includes('verif')) active.add('stage-verify');
        if (phase.includes('report') || phase.includes('export')) active.add('stage-report');
        // If no specific phase, assume scanning
        if (!phase) active.add('stage-scan');
      }
    });
    return active;
  }, [jobs]);

  // Build workflow nodes combining pipeline stages and agents
  const nodes = useMemo((): WorkflowNode[] => {
    // Pipeline stage nodes
    const stageNodes: WorkflowNode[] = PIPELINE_STAGES.map((stage) => ({
      id: stage.id,
      type: stage.type,
      label: stage.label,
      status: activeStages.has(stage.id) ? 'working' : 'idle',
    }));

    // Agent nodes
    const agentNodes: WorkflowNode[] = agents.map((agent) => ({
      id: `agent-${agent.id}`,
      type: 'agent' as WorkflowNodeType,
      label: agent.name || agent.id,
      status:
        agent.status === 'working' || agent.status === 'busy'
          ? 'working'
          : agent.status === 'error'
            ? 'error'
            : 'idle',
      agent,
    }));

    return [...stageNodes, ...agentNodes];
  }, [agents, activeStages]);

  // Build links including agent assignments
  const links = useMemo((): WorkflowLink[] => {
    const allLinks = [...PIPELINE_LINKS];

    // Add links from agents to stages they're working on
    agents.forEach((agent) => {
      if (agent.status === 'working' && agent.current_task) {
        const task = agent.current_task.toLowerCase();
        let targetStage = 'stage-scan'; // default

        if (task.includes('ingest') || task.includes('upload')) targetStage = 'stage-ingest';
        else if (task.includes('chunk') || task.includes('process')) targetStage = 'stage-chunk';
        else if (task.includes('scan') || task.includes('audit')) targetStage = 'stage-scan';
        else if (task.includes('verif')) targetStage = 'stage-verify';
        else if (task.includes('report')) targetStage = 'stage-report';

        allLinks.push({
          source: `agent-${agent.id}`,
          target: targetStage,
          type: 'assigns',
          active: true,
        });
      }
    });

    // Mark active flow links
    return allLinks.map((link) => ({
      ...link,
      active:
        link.type === 'flow' && activeStages.has(link.source) && activeStages.has(link.target),
    }));
  }, [agents, activeStages]);

  // D3 visualization
  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3Select.select(svgRef.current);
    svg.selectAll('*').remove();

    // Create container group for zoom/pan
    const g = svg.append('g').attr('class', 'workflow-container');

    // Create gradient definitions for active links
    const defs = svg.append('defs');

    // Glow filter for active elements
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Arrow markers
    defs
      .selectAll('marker')
      .data(['flow', 'flow-active', 'assigns'])
      .join('marker')
      .attr('id', (d) => `arrow-${d}`)
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 25)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('fill', (d) => (d === 'assigns' ? '#00ffff' : d === 'flow-active' ? '#39ff14' : '#666'))
      .attr('d', 'M0,-5L10,0L0,5');

    // Position pipeline stages horizontally
    const stageSpacing = width / (PIPELINE_STAGES.length + 1);
    const stageY = height * 0.35;

    nodes.forEach((node) => {
      if (node.type !== 'agent') {
        const stageIndex = PIPELINE_STAGES.findIndex((s) => s.id === node.id);
        if (stageIndex >= 0) {
          node.fx = stageSpacing * (stageIndex + 1);
          node.fy = stageY;
        }
      }
    });

    // Create simulation
    const simulation = d3
      .forceSimulation<WorkflowNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<WorkflowNode, WorkflowLink>(links)
          .id((d) => d.id)
          .distance(80)
          .strength(0.3),
      )
      .force('charge', d3.forceManyBody().strength(-200))
      .force(
        'y',
        d3.forceY<WorkflowNode>(height * 0.7).strength((d) => (d.type === 'agent' ? 0.1 : 0)),
      )
      .force('collision', d3.forceCollide().radius(35));

    // Draw links
    const link = g
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', (d) => (d.type === 'assigns' ? '#00ffff80' : d.active ? '#39ff14' : '#444'))
      .attr('stroke-width', (d) => (d.active ? 3 : 2))
      .attr('stroke-dasharray', (d) => (d.type === 'assigns' ? '5,5' : 'none'))
      .attr(
        'marker-end',
        (d) =>
          `url(#arrow-${d.type === 'assigns' ? 'assigns' : d.active ? 'flow-active' : 'flow'})`,
      )
      .attr('filter', (d) => (d.active ? 'url(#glow)' : 'none'));

    // Draw nodes
    const node = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'node')
      .attr('cursor', 'pointer')
      .call(drag(simulation) as never);

    // Node backgrounds (for glow effect)
    node
      .filter((d) => d.status === 'working')
      .append('circle')
      .attr('r', (d) => NODE_RADIUS[d.type] + 4)
      .attr('fill', 'none')
      .attr('stroke', (d) => STATUS_COLORS[d.status])
      .attr('stroke-width', 2)
      .attr('opacity', 0.5)
      .attr('filter', 'url(#glow)')
      .attr('class', 'pulse-ring');

    // Node circles
    node
      .append('circle')
      .attr('r', (d) => NODE_RADIUS[d.type])
      .attr('fill', (d) =>
        d.type === 'agent' ? STATUS_COLORS[d.status] || '#666' : NODE_COLORS[d.type],
      )
      .attr('stroke', '#000')
      .attr('stroke-width', 2)
      .attr('opacity', 0.9);

    // Status indicator for agents
    node
      .filter((d) => d.type === 'agent')
      .append('circle')
      .attr('cx', 10)
      .attr('cy', -10)
      .attr('r', 5)
      .attr('fill', (d) => STATUS_COLORS[d.status] || '#666')
      .attr('stroke', '#000')
      .attr('stroke-width', 1);

    // Node labels
    node
      .append('text')
      .attr('dy', (d) => NODE_RADIUS[d.type] + 14)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('fill', '#ccc')
      .attr('font-family', 'monospace')
      .text((d) => d.label);

    // Tooltips
    node.append('title').text((d) => {
      if (d.agent) {
        return `${d.agent.name}\nModel: ${d.agent.model}\nStatus: ${d.agent.status}\n${d.agent.current_task || ''}`;
      }
      return `${d.label}\nStatus: ${d.status}`;
    });

    // Click handler
    node.on('click', (event, d) => {
      event.stopPropagation();
      setSelectedNode(d);
      onNodeClick?.(d);
      if (d.agent) {
        onAgentClick?.(d.agent);
      }
    });

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d as unknown as SimulatedWorkflowLink).source.x ?? 0)
        .attr('y1', (d) => (d as unknown as SimulatedWorkflowLink).source.y ?? 0)
        .attr('x2', (d) => (d as unknown as SimulatedWorkflowLink).target.x ?? 0)
        .attr('y2', (d) => (d as unknown as SimulatedWorkflowLink).target.y ?? 0);

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Zoom behavior
    const zoom = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Drag behavior helper
    function drag(simulation: d3.Simulation<WorkflowNode, undefined>) {
      type DragEvent = D3DragEvent<SVGGElement, WorkflowNode, WorkflowNode>;

      function dragstarted(event: DragEvent) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
      }

      function dragged(event: DragEvent) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
      }

      function dragended(event: DragEvent) {
        if (!event.active) simulation.alphaTarget(0);
        // Keep pipeline stages fixed, release agents
        if (!PIPELINE_STAGES.some((s) => s.id === event.subject.id)) {
          event.subject.fx = null;
          event.subject.fy = null;
        }
      }

      return d3Drag<SVGGElement, WorkflowNode>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended);
    }

    // Add CSS animation for pulse
    const style = document.createElement('style');
    style.textContent = `
      @keyframes pulse {
        0% { opacity: 0.5; transform: scale(1); }
        50% { opacity: 0.8; transform: scale(1.1); }
        100% { opacity: 0.5; transform: scale(1); }
      }
      .pulse-ring {
        animation: pulse 2s ease-in-out infinite;
        transform-origin: center;
      }
    `;
    document.head.appendChild(style);

    return () => {
      simulation.stop();
      style.remove();
    };
  }, [nodes, links, width, height, onNodeClick, onAgentClick]);

  // Calculate active job summary
  const activeJobs = jobs.filter((j) => j.status === 'running');
  const totalProgress =
    activeJobs.length > 0
      ? activeJobs.reduce((sum, j) => sum + (j.progress ?? 0), 0) / activeJobs.length
      : 0;

  return (
    <div className="relative">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 px-2">
        <div className="text-xs font-theme-data text-text-muted">PIPELINE STATUS</div>
        {activeJobs.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
            <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
              {activeJobs.length} ACTIVE • {Math.round(totalProgress * 100)}%
            </span>
          </div>
        )}
      </div>

      {/* SVG Canvas */}
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="bg-bg/50 rounded border border-[var(--accent)]/20"
        style={{ minHeight: '300px' }}
      />

      {/* Selected Node Details */}
      {selectedNode && (
        <div className="absolute top-12 right-2 w-64 p-3 bg-surface border border-[var(--accent)]/30 rounded shadow-lg z-10">
          <div className="flex items-center justify-between mb-2">
            <span
              className={`px-2 py-0.5 rounded text-xs font-theme-data ${
                selectedNode.status === 'working'
                  ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                  : selectedNode.status === 'error'
                    ? 'bg-acid-red/20 text-acid-red'
                    : 'bg-[var(--accent)]/20 text-[var(--accent)]'
              }`}
            >
              {selectedNode.status.toUpperCase()}
            </span>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-text-muted hover:text-text text-xs"
            >
              [X]
            </button>
          </div>

          <div className="font-theme-data text-sm mb-2">{selectedNode.label}</div>

          {selectedNode.agent && (
            <div className="space-y-1 text-xs font-theme-data text-text-muted">
              <div>Model: {selectedNode.agent.model}</div>
              <div>Requests: {selectedNode.agent.requests_today ?? 0}</div>
              <div>Tokens: {(selectedNode.agent.tokens_used ?? 0).toLocaleString()}</div>
              {selectedNode.agent.current_task && (
                <div className="mt-2 p-2 bg-bg rounded text-[var(--acid-cyan)]">
                  {selectedNode.agent.current_task}
                </div>
              )}
            </div>
          )}

          {!selectedNode.agent && (
            <div className="text-xs font-theme-data text-text-muted">
              Pipeline stage: {selectedNode.type.toUpperCase()}
            </div>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-2 left-2 flex gap-4 text-xs font-theme-data text-text-muted">
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-full bg-[var(--accent)]" />
          <span>Idle</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
          <span>Working</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-full bg-acid-red" />
          <span>Error</span>
        </div>
      </div>

      {/* Controls hint */}
      <div className="absolute bottom-2 right-2 text-xs font-theme-data text-text-muted">
        Scroll to zoom • Drag agents
      </div>
    </div>
  );
}

export default AgentWorkflowVisualization;
