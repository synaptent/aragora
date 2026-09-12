'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { withErrorBoundary } from './PanelErrorBoundary';
import { API_BASE_URL } from '@/config';
import { extractLeaderboardAgentNames } from '@/lib/leaderboard';

interface RelationshipEntry {
  agent: string;
  score: number;
  debate_count?: number;
}

// Network graph node
interface NetworkNode {
  id: string;
  x: number;
  y: number;
  type: 'center' | 'rival' | 'ally' | 'influence' | 'influenced_by';
}

// Network graph edge
interface NetworkEdge {
  source: string;
  target: string;
  type: 'rival' | 'ally' | 'influence' | 'influenced_by';
  strength: number;
}

interface AgentNetwork {
  agent: string;
  influences: RelationshipEntry[];
  influenced_by: RelationshipEntry[];
  rivals: RelationshipEntry[];
  allies: RelationshipEntry[];
}

interface SignificantMoment {
  type: string;
  description: string;
  significance: number;
  debate_id?: string;
  timestamp?: string;
}

interface AgentNetworkPanelProps {
  selectedAgent?: string;
  apiBase?: string;
  onAgentSelect?: (agent: string) => void;
}

const DEFAULT_API_BASE = API_BASE_URL;

// SVG Network Graph Component
function NetworkGraph({
  network,
  onNodeClick,
}: {
  network: AgentNetwork;
  onNodeClick?: (agent: string) => void;
}) {
  const width = 400;
  const height = 300;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = 100;

  // Build nodes and edges
  const { nodes, edges } = useMemo(() => {
    const nodeList: NetworkNode[] = [];
    const edgeList: NetworkEdge[] = [];
    const seenAgents = new Set<string>();

    // Center node (the selected agent)
    nodeList.push({ id: network.agent, x: centerX, y: centerY, type: 'center' });
    seenAgents.add(network.agent);

    // Collect all related agents with their types
    const relatedAgents: { agent: string; type: NetworkEdge['type']; score: number }[] = [];

    network.rivals?.forEach((r) => {
      if (!seenAgents.has(r.agent)) {
        relatedAgents.push({ agent: r.agent, type: 'rival', score: r.score });
        seenAgents.add(r.agent);
      }
    });
    network.allies?.forEach((a) => {
      if (!seenAgents.has(a.agent)) {
        relatedAgents.push({ agent: a.agent, type: 'ally', score: a.score });
        seenAgents.add(a.agent);
      }
    });
    network.influences?.forEach((i) => {
      if (!seenAgents.has(i.agent)) {
        relatedAgents.push({ agent: i.agent, type: 'influence', score: i.score });
        seenAgents.add(i.agent);
      }
    });
    network.influenced_by?.forEach((i) => {
      if (!seenAgents.has(i.agent)) {
        relatedAgents.push({ agent: i.agent, type: 'influenced_by', score: i.score });
        seenAgents.add(i.agent);
      }
    });

    // Position nodes in a circle around the center
    const angleStep = (2 * Math.PI) / Math.max(relatedAgents.length, 1);
    relatedAgents.forEach((rel, idx) => {
      const angle = idx * angleStep - Math.PI / 2;
      nodeList.push({
        id: rel.agent,
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
        type: rel.type,
      });
      edgeList.push({
        source: network.agent,
        target: rel.agent,
        type: rel.type,
        strength: rel.score,
      });
    });

    return { nodes: nodeList, edges: edgeList };
  }, [network, centerX, centerY, radius]);

  const getNodeColor = (type: NetworkNode['type']) => {
    switch (type) {
      case 'center':
        return '#22d3ee'; // cyan
      case 'rival':
        return '#ef4444'; // red
      case 'ally':
        return '#22c55e'; // green
      case 'influence':
        return '#3b82f6'; // blue
      case 'influenced_by':
        return '#a855f7'; // purple
      default:
        return '#71717a';
    }
  };

  const getEdgeColor = (type: NetworkEdge['type']) => {
    switch (type) {
      case 'rival':
        return 'rgba(239, 68, 68, 0.5)';
      case 'ally':
        return 'rgba(34, 197, 94, 0.5)';
      case 'influence':
        return 'rgba(59, 130, 246, 0.5)';
      case 'influenced_by':
        return 'rgba(168, 85, 247, 0.5)';
      default:
        return 'rgba(113, 113, 122, 0.5)';
    }
  };

  const nodeById = useMemo(() => {
    const map: Record<string, NetworkNode> = {};
    nodes.forEach((n) => {
      map[n.id] = n;
    });
    return map;
  }, [nodes]);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-64 bg-zinc-100/50 dark:bg-zinc-900/50 rounded-lg"
    >
      {/* Edges */}
      {edges.map((edge, idx) => {
        const source = nodeById[edge.source];
        const target = nodeById[edge.target];
        if (!source || !target) return null;
        return (
          <line
            key={idx}
            x1={source.x}
            y1={source.y}
            x2={target.x}
            y2={target.y}
            stroke={getEdgeColor(edge.type)}
            strokeWidth={Math.max(1, edge.strength * 3)}
            strokeDasharray={edge.type === 'rival' ? '4,2' : undefined}
          />
        );
      })}

      {/* Nodes */}
      {nodes.map((node) => (
        <g
          key={node.id}
          transform={`translate(${node.x}, ${node.y})`}
          className="cursor-pointer focus:outline-none"
          onClick={() => onNodeClick?.(node.id)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onNodeClick?.(node.id);
            }
          }}
          role="button"
          tabIndex={0}
          aria-label={`${node.id} - ${node.type}${node.type === 'center' ? ' (selected)' : ''}`}
        >
          <circle
            r={node.type === 'center' ? 20 : 15}
            fill={getNodeColor(node.type)}
            stroke={node.type === 'center' ? '#fff' : 'transparent'}
            strokeWidth={node.type === 'center' ? 2 : 0}
            className="hover:opacity-80 transition-opacity"
          />
          <text
            textAnchor="middle"
            dy={node.type === 'center' ? 35 : 28}
            className="text-[10px] fill-zinc-400"
          >
            {node.id.length > 12 ? node.id.slice(0, 10) + '...' : node.id}
          </text>
        </g>
      ))}

      {/* Legend */}
      <g transform="translate(10, 10)">
        <circle cx="6" cy="6" r="4" fill="#ef4444" />
        <text x="14" y="9" className="text-[8px] fill-zinc-500">
          Rival
        </text>
        <circle cx="6" cy="20" r="4" fill="#22c55e" />
        <text x="14" y="23" className="text-[8px] fill-zinc-500">
          Ally
        </text>
        <circle cx="56" cy="6" r="4" fill="#3b82f6" />
        <text x="64" y="9" className="text-[8px] fill-zinc-500">
          Influences
        </text>
        <circle cx="56" cy="20" r="4" fill="#a855f7" />
        <text x="64" y="23" className="text-[8px] fill-zinc-500">
          Influenced By
        </text>
      </g>
    </svg>
  );
}

function AgentNetworkPanelComponent({
  selectedAgent,
  apiBase = DEFAULT_API_BASE,
  onAgentSelect,
}: AgentNetworkPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph');
  const [network, setNetwork] = useState<AgentNetwork | null>(null);
  const [moments, setMoments] = useState<SignificantMoment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentInput, setAgentInput] = useState(selectedAgent || '');
  const [availableAgents, setAvailableAgents] = useState<string[]>([]);
  const initialFetchDone = useRef(false);

  // Fetch available agents from leaderboard - only once on mount
  useEffect(() => {
    if (initialFetchDone.current) return;
    initialFetchDone.current = true;

    fetch(`${apiBase}/api/leaderboard?limit=20`)
      .then((res) => {
        // Don't retry on rate limit - gracefully handle
        if (res.status === 429) return { agents: [] };
        return res.json();
      })
      .then((data: { agents?: Array<{ name: string }>; leaderboard?: Array<{ name: string }> }) => {
        const agents = extractLeaderboardAgentNames(data);
        setAvailableAgents(agents);
        if (agents.length > 0 && !agentInput) {
          setAgentInput(agents[0]);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Intentionally exclude agentInput to prevent re-fetching on selection
  }, [apiBase]);

  const fetchNetwork = useCallback(
    async (agent: string) => {
      if (!agent) return;

      setLoading(true);
      setError(null);

      try {
        // Fetch network and moments in parallel
        const [networkRes, momentsRes] = await Promise.all([
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agent)}/network`),
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agent)}/moments?limit=5`),
        ]);

        if (!networkRes.ok) {
          throw new Error(`Failed to fetch network: ${networkRes.statusText}`);
        }

        const networkData = await networkRes.json();
        setNetwork(networkData);

        // Moments are optional - don't fail if not available
        if (momentsRes.ok) {
          const momentsData = await momentsRes.json();
          setMoments(momentsData.moments || []);
        } else {
          setMoments([]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load network');
      } finally {
        setLoading(false);
      }
    },
    [apiBase],
  );

  useEffect(() => {
    if (selectedAgent) {
      setAgentInput(selectedAgent);
      fetchNetwork(selectedAgent);
    }
  }, [selectedAgent, fetchNetwork]);

  const handleFetch = () => {
    if (agentInput) {
      fetchNetwork(agentInput);
    }
  };

  const renderRelationshipList = (
    title: string,
    items: RelationshipEntry[],
    icon: string,
    colorClass: string,
  ) => {
    if (!items || items.length === 0) {
      return <div className="text-zinc-500 text-sm">No {title.toLowerCase()} data</div>;
    }

    return (
      <div>
        <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-500 dark:text-zinc-400 mb-2 flex items-center gap-2">
          <span>{icon}</span> {title}
        </h4>
        <div className="space-y-1" role="list" aria-label={title}>
          {items.map((item) => (
            <button
              key={item.agent}
              type="button"
              className={`w-full flex items-center justify-between p-2 rounded ${colorClass} cursor-pointer hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-500`}
              onClick={() => {
                setAgentInput(item.agent);
                fetchNetwork(item.agent);
                onAgentSelect?.(item.agent);
              }}
              aria-label={`View ${item.agent}'s network - Score: ${(item.score * 100).toFixed(0)}%${item.debate_count !== undefined ? `, ${item.debate_count} debates` : ''}`}
            >
              <span className="font-medium">{item.agent}</span>
              <div className="flex items-center gap-2 text-xs">
                <span className="opacity-75">Score: {(item.score * 100).toFixed(0)}%</span>
                {item.debate_count !== undefined && (
                  <span className="opacity-50">({item.debate_count} debates)</span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  };

  // Collapsed view
  if (!isExpanded) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-expanded={false}
        aria-label={`Expand Agent Network panel${network ? ` for ${network.agent}` : ''}`}
        className="panel panel-compact cursor-pointer"
        onClick={() => setIsExpanded(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsExpanded(true);
          }
        }}
      >
        <div className="flex items-center justify-between">
          <h3 className="panel-title-sm flex items-center gap-2">
            <span className="text-accent">{'>'}</span>
            AGENT_NETWORK {network ? `[${network.agent}]` : ''}
          </h3>
          <div className="flex items-center gap-2">
            {network && (
              <span className="text-xs font-theme-data text-text-muted">
                {network.rivals?.length || 0} rivals, {network.allies?.length || 0} allies
              </span>
            )}
            <span className="panel-toggle">[EXPAND]</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span className="text-accent">{'>'}</span>
          AGENT_NETWORK
        </h3>
        <button
          onClick={() => setIsExpanded(false)}
          aria-expanded={true}
          aria-label="Collapse Agent Network panel"
          className="panel-toggle hover:text-accent"
        >
          [COLLAPSE]
        </button>
      </div>

      {/* Agent Selector */}
      <div className="flex gap-2 mb-4">
        <select
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          className="flex-1 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300"
        >
          <option value="">Select an agent...</option>
          {availableAgents.map((agent) => (
            <option key={agent} value={agent}>
              {agent}
            </option>
          ))}
        </select>
        <button
          onClick={handleFetch}
          disabled={!agentInput || loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded"
        >
          {loading ? 'Loading...' : 'View Network'}
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Network Display */}
      {network && (
        <div className="space-y-4">
          {/* Agent Header with View Toggle */}
          <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-lg font-medium text-white">
                {network.agent}&apos;s Relationship Network
              </h4>
              <div className="flex gap-1" role="group" aria-label="View mode">
                <button
                  onClick={() => setViewMode('graph')}
                  aria-pressed={viewMode === 'graph'}
                  className={`px-2 py-1 text-xs rounded ${
                    viewMode === 'graph'
                      ? 'bg-blue-600 text-white'
                      : 'bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-500 dark:text-zinc-400 hover:bg-zinc-300 dark:hover:bg-zinc-600'
                  }`}
                >
                  Graph
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  aria-pressed={viewMode === 'list'}
                  className={`px-2 py-1 text-xs rounded ${
                    viewMode === 'list'
                      ? 'bg-blue-600 text-white'
                      : 'bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-500 dark:text-zinc-400 hover:bg-zinc-300 dark:hover:bg-zinc-600'
                  }`}
                >
                  List
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="text-zinc-500 dark:text-zinc-400">
                <span className="text-white font-medium">{network.rivals?.length || 0}</span> rivals
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">
                <span className="text-white font-medium">{network.allies?.length || 0}</span> allies
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">
                <span className="text-white font-medium">{network.influences?.length || 0}</span>{' '}
                influenced
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">
                <span className="text-white font-medium">{network.influenced_by?.length || 0}</span>{' '}
                influencers
              </div>
            </div>
          </div>

          {/* Graph View */}
          {viewMode === 'graph' && (
            <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
              <NetworkGraph
                network={network}
                onNodeClick={(agent) => {
                  if (agent !== network.agent) {
                    setAgentInput(agent);
                    fetchNetwork(agent);
                    onAgentSelect?.(agent);
                  }
                }}
              />
              <p className="text-xs text-zinc-500 mt-2 text-center">
                Click on a node to explore that agent&apos;s network
              </p>
            </div>
          )}

          {/* Relationship Sections (List View) */}
          {viewMode === 'list' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Rivals */}
              <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
                {renderRelationshipList(
                  'Rivals',
                  network.rivals,
                  '⚔️',
                  'bg-red-900/20 border border-red-800/30 text-red-400',
                )}
              </div>

              {/* Allies */}
              <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
                {renderRelationshipList(
                  'Allies',
                  network.allies,
                  '🤝',
                  'bg-green-900/20 border border-green-800/30 text-green-400',
                )}
              </div>

              {/* Influences */}
              <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
                {renderRelationshipList(
                  'Influences',
                  network.influences,
                  '📤',
                  'bg-blue-900/20 border border-blue-800/30 text-blue-400',
                )}
              </div>

              {/* Influenced By */}
              <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
                {renderRelationshipList(
                  'Influenced By',
                  network.influenced_by,
                  '📥',
                  'bg-purple-900/20 border border-purple-800/30 text-purple-400',
                )}
              </div>
            </div>
          )}

          {/* Significant Moments */}
          {moments.length > 0 && (
            <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
              <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3 flex items-center gap-2">
                <span>⭐</span> Significant Moments
              </h4>
              <div className="space-y-2">
                {moments.map((moment, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded bg-yellow-900/20 border border-yellow-800/30"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-yellow-400 uppercase">
                        {moment.type.replace(/_/g, ' ')}
                      </span>
                      <span className="text-xs text-zinc-500">
                        {(moment.significance * 100).toFixed(0)}% significance
                      </span>
                    </div>
                    <p className="text-sm text-zinc-700 dark:text-zinc-300">{moment.description}</p>
                    {moment.debate_id && (
                      <span className="text-xs text-zinc-500 mt-1 block">
                        Debate: {moment.debate_id.slice(0, 8)}...
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty State */}
      {!network && !loading && !error && (
        <div className="text-center py-8 text-zinc-500">
          Select an agent to view their relationship network
        </div>
      )}

      <div className="mt-3 text-[10px] text-text-muted font-theme-data">
        Agent rivalry and alliance relationship visualization
      </div>
    </div>
  );
}

// Wrap with error boundary for graceful error handling
export const AgentNetworkPanel = withErrorBoundary(AgentNetworkPanelComponent, 'Agent Network');
export default AgentNetworkPanel;
