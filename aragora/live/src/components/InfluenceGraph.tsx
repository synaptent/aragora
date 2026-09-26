'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3-force';
import * as d3Select from 'd3-selection';
import { zoom as d3Zoom } from 'd3-zoom';
import { drag as d3Drag, type D3DragEvent } from 'd3-drag';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

// =============================================================================
// Types
// =============================================================================

interface BeliefNode extends d3.SimulationNodeDatum {
  id: string;
  claim_id: string;
  statement: string;
  author: string;
  centrality: number;
  is_crux: boolean;
  crux_score?: number;
  entropy?: number;
  belief?: { true_prob: number; false_prob: number; uncertain_prob: number };
}

interface InfluenceLink {
  source: string;
  target: string;
  weight: number;
  type: 'supports' | 'opposes' | 'influences';
}

// D3 simulation modifies links to reference node objects
interface SimulatedInfluenceLink extends d3.SimulationLinkDatum<BeliefNode> {
  source: BeliefNode;
  target: BeliefNode;
  weight: number;
  type: 'supports' | 'opposes' | 'influences';
}

interface NetworkData {
  nodes: BeliefNode[];
  links: InfluenceLink[];
  metadata?: { debate_id: string; total_claims: number; crux_count: number };
}

interface InfluenceGraphProps {
  debateId?: string;
  data?: NetworkData;
  width?: number;
  height?: number;
  apiBase?: string;
  onNodeSelect?: (node: BeliefNode | null) => void;
  highlightCruxes?: boolean;
}

// =============================================================================
// Constants
// =============================================================================

const AGENT_COLORS: Record<string, string> = {
  claude: '#39ff14',
  gpt4: '#ff39ff',
  gemini: '#39ffff',
  mistral: '#ffff39',
  grok: '#ff3939',
  default: '#888888',
};

const getAgentColor = (agent: string): string => {
  const normalized = agent.toLowerCase();
  for (const [key, color] of Object.entries(AGENT_COLORS)) {
    if (normalized.includes(key)) return color;
  }
  return AGENT_COLORS.default;
};

// =============================================================================
// Component
// =============================================================================

export function InfluenceGraph({
  debateId,
  data: initialData,
  width = 800,
  height = 600,
  apiBase = API_BASE_URL,
  onNodeSelect,
  highlightCruxes = true,
}: InfluenceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<NetworkData | null>(initialData || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<BeliefNode | null>(null);
  const [showLabels, setShowLabels] = useState(true);

  const { tokens, isLoading: authLoading } = useAuth();

  // Fetch network data
  const fetchNetworkData = useCallback(async () => {
    if (!debateId) return;

    if (authLoading || !tokens?.access_token) {
      setLoading(false);
      setError('Login required to load belief network');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const headers: HeadersInit = {};
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiBase}/api/belief-network/${debateId}/graph`, { headers });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const networkData = await response.json();
      setData(networkData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch network');
    } finally {
      setLoading(false);
    }
  }, [debateId, apiBase, tokens?.access_token, authLoading]);

  useEffect(() => {
    if (debateId && !initialData) {
      fetchNetworkData();
    }
  }, [debateId, initialData, fetchNetworkData]);

  // D3 visualization
  useEffect(() => {
    if (!svgRef.current || !data || data.nodes.length === 0) return;

    const svg = d3Select.select(svgRef.current);
    svg.selectAll('*').remove();

    // Create container for zoom/pan
    const g = svg.append('g').attr('class', 'graph-container');

    // Add glow filter for crux nodes
    const defs = svg.append('defs');

    const glowFilter = defs
      .append('filter')
      .attr('id', 'crux-glow')
      .attr('x', '-50%')
      .attr('y', '-50%')
      .attr('width', '200%')
      .attr('height', '200%');

    glowFilter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');

    const feMerge = glowFilter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Arrow markers
    defs
      .selectAll('marker')
      .data(['supports', 'opposes', 'influences'])
      .join('marker')
      .attr('id', (d) => `arrow-${d}`)
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 25)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('fill', (d) => (d === 'opposes' ? '#ff3939' : d === 'supports' ? '#39ff14' : '#666'))
      .attr('d', 'M0,-5L10,0L0,5');

    // Create simulation with proper typing
    const simulation = d3
      .forceSimulation<BeliefNode>(data.nodes)
      .force(
        'link',
        d3
          .forceLink<BeliefNode, InfluenceLink>(data.links)
          .id((d) => d.id)
          .distance((d) => 150 - d.weight * 50)
          .strength((d) => d.weight * 0.5),
      )
      .force(
        'charge',
        d3.forceManyBody<BeliefNode>().strength((d) => -200 - d.centrality * 300),
      )
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force(
        'collision',
        d3.forceCollide<BeliefNode>().radius((d) => 20 + d.centrality * 30),
      );

    // Draw links
    const link = g
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(data.links)
      .join('line')
      .attr('stroke', (d) =>
        d.type === 'opposes' ? '#ff393960' : d.type === 'supports' ? '#39ff1460' : '#66666660',
      )
      .attr('stroke-width', (d) => 1 + d.weight * 3)
      .attr('marker-end', (d) => `url(#arrow-${d.type})`);

    // Draw nodes
    const node = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(data.nodes)
      .join('g')
      .attr('class', 'node')
      .attr('cursor', 'pointer')
      .call(drag(simulation) as never);

    // Node circles
    node
      .append('circle')
      .attr('r', (d) => 8 + d.centrality * 20)
      .attr('fill', (d) => getAgentColor(d.author))
      .attr('stroke', (d) => (d.is_crux && highlightCruxes ? '#ffff00' : '#000'))
      .attr('stroke-width', (d) => (d.is_crux && highlightCruxes ? 3 : 1.5))
      .attr('opacity', (d) => 0.7 + d.centrality * 0.3)
      .attr('filter', (d) => (d.is_crux && highlightCruxes ? 'url(#crux-glow)' : null));

    // Crux indicator
    node
      .filter((d) => d.is_crux && highlightCruxes)
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 4)
      .attr('font-size', '12px')
      .attr('fill', '#000')
      .attr('font-weight', 'bold')
      .text('!');

    // Labels
    if (showLabels) {
      node
        .append('text')
        .attr('dx', (d) => 12 + d.centrality * 20)
        .attr('dy', 4)
        .attr('font-size', '10px')
        .attr('fill', '#aaa')
        .attr('font-family', 'monospace')
        .text((d) => d.author);
    }

    // Tooltips
    node.append('title').text((d) => {
      const cruxLabel = d.is_crux ? ' [CRUX]' : '';
      return `${d.author}${cruxLabel}\n${d.statement.slice(0, 100)}...`;
    });

    // Click handler
    node.on('click', (event, d) => {
      event.stopPropagation();
      setSelectedNode(d);
      onNodeSelect?.(d);
    });

    // Background click to deselect
    svg.on('click', () => {
      setSelectedNode(null);
      onNodeSelect?.(null);
    });

    // Update positions
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d as unknown as SimulatedInfluenceLink).source.x ?? 0)
        .attr('y1', (d) => (d as unknown as SimulatedInfluenceLink).source.y ?? 0)
        .attr('x2', (d) => (d as unknown as SimulatedInfluenceLink).target.x ?? 0)
        .attr('y2', (d) => (d as unknown as SimulatedInfluenceLink).target.y ?? 0);

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Zoom behavior
    const zoom = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Drag helper
    function drag(simulation: d3.Simulation<BeliefNode, undefined>) {
      type DragEvent = D3DragEvent<SVGGElement, BeliefNode, BeliefNode>;

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
        event.subject.fx = null;
        event.subject.fy = null;
      }

      return d3Drag<SVGGElement, BeliefNode>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended);
    }

    return () => {
      simulation.stop();
    };
  }, [data, width, height, highlightCruxes, showLabels, onNodeSelect]);

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 bg-surface border border-border rounded-lg">
        <div className="text-[var(--accent)] font-theme-data animate-pulse">
          Loading belief network...
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="p-4 bg-acid-red/10 border border-acid-red/30 rounded-lg">
        <div className="text-acid-red font-theme-data text-sm mb-2">
          Failed to load network: {error}
        </div>
        <button
          onClick={fetchNetworkData}
          className="px-3 py-1 text-xs font-theme-data bg-surface border border-acid-red/30 rounded hover:border-acid-red/50"
        >
          [RETRY]
        </button>
      </div>
    );
  }

  // Empty state
  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 bg-surface border border-border rounded-lg">
        <div className="text-text-muted font-theme-data text-sm">
          No belief network data available
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Controls */}
      <div className="absolute top-2 left-2 z-10 flex gap-2">
        <button
          onClick={() => setShowLabels(!showLabels)}
          className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
            showLabels
              ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30'
              : 'bg-surface text-text-muted border border-border'
          }`}
        >
          {showLabels ? '[LABELS ON]' : '[LABELS OFF]'}
        </button>
        {debateId && (
          <button
            onClick={fetchNetworkData}
            className="px-2 py-1 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)]/50"
          >
            [REFRESH]
          </button>
        )}
      </div>

      {/* Legend */}
      <div className="absolute top-2 right-2 z-10 p-2 bg-surface/90 border border-border rounded text-xs font-theme-data">
        <div className="text-text-muted mb-1">LEGEND</div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-[#39ff14]" />
            <span className="text-text-muted">Claude</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-[#ff39ff]" />
            <span className="text-text-muted">GPT-4</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-[#39ffff]" />
            <span className="text-text-muted">Gemini</span>
          </div>
          {highlightCruxes && (
            <div className="flex items-center gap-2 mt-2 pt-2 border-t border-border">
              <div className="w-3 h-3 rounded-full bg-[#ffff00] border-2 border-yellow-400" />
              <span className="text-[var(--acid-yellow)]">Crux claim</span>
            </div>
          )}
        </div>
      </div>

      {/* Graph */}
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="bg-bg/50 rounded border border-[var(--accent)]/20"
      />

      {/* Selected Node Panel */}
      {selectedNode && (
        <div className="absolute bottom-2 left-2 right-2 p-4 bg-surface border border-[var(--acid-cyan)]/30 rounded-lg shadow-lg max-w-md">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: getAgentColor(selectedNode.author) }}
              />
              <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                {selectedNode.author}
              </span>
              {selectedNode.is_crux && (
                <span className="px-1.5 py-0.5 text-xs font-theme-data bg-acid-yellow/20 text-[var(--acid-yellow)] rounded">
                  CRUX
                </span>
              )}
            </div>
            <button
              onClick={() => {
                setSelectedNode(null);
                onNodeSelect?.(null);
              }}
              className="text-text-muted hover:text-text text-xs font-theme-data"
            >
              [X]
            </button>
          </div>

          <p className="font-theme-data text-sm text-text mb-3 line-clamp-3">
            {selectedNode.statement}
          </p>

          <div className="flex flex-wrap gap-3 text-xs font-theme-data">
            <span className="text-text-muted">
              Centrality:{' '}
              <span className="text-[var(--accent)]">
                {(selectedNode.centrality * 100).toFixed(1)}%
              </span>
            </span>
            {selectedNode.crux_score !== undefined && (
              <span className="text-text-muted">
                Crux Score:{' '}
                <span className="text-[var(--acid-yellow)]">
                  {selectedNode.crux_score.toFixed(3)}
                </span>
              </span>
            )}
            {selectedNode.entropy !== undefined && (
              <span className="text-text-muted">
                Entropy:{' '}
                <span
                  className={
                    selectedNode.entropy >= 0.8
                      ? 'text-acid-red'
                      : selectedNode.entropy >= 0.5
                        ? 'text-[var(--acid-yellow)]'
                        : 'text-[var(--accent)]'
                  }
                >
                  {selectedNode.entropy.toFixed(2)}
                </span>
              </span>
            )}
          </div>

          {selectedNode.belief && (
            <div className="mt-2 flex gap-2">
              <span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">
                T: {(selectedNode.belief.true_prob * 100).toFixed(0)}%
              </span>
              <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded text-xs">
                F: {(selectedNode.belief.false_prob * 100).toFixed(0)}%
              </span>
              <span className="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs">
                ?: {(selectedNode.belief.uncertain_prob * 100).toFixed(0)}%
              </span>
            </div>
          )}
        </div>
      )}

      {/* Stats footer */}
      {data.metadata && (
        <div className="absolute bottom-2 right-2 px-2 py-1 bg-surface/80 rounded text-xs font-theme-data text-text-muted">
          {data.metadata.total_claims} claims | {data.metadata.crux_count} cruxes
        </div>
      )}
    </div>
  );
}

export default InfluenceGraph;
