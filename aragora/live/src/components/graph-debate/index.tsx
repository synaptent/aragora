'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import type { StreamEvent } from '@/types/events';
import { Skeleton } from '../Skeleton';
import { useGraphDebateWebSocket } from '@/hooks/useGraphDebateWebSocket';
import { API_BASE_URL } from '@/config';

import type { GraphDebate } from './types';
import { getBranchColor, getBranchBgColor } from './utils';
import { GraphVisualization } from './GraphVisualization';
import { NodeDetailPanel } from './NodeDetailPanel';
import { MobileGraphListView } from './MobileGraphListView';
import { useIsMobile } from './hooks';

export interface GraphDebateBrowserProps {
  events?: StreamEvent[];
  initialDebateId?: string | null;
}

export function GraphDebateBrowser({ events = [], initialDebateId }: GraphDebateBrowserProps) {
  const [debates, setDebates] = useState<GraphDebate[]>([]);
  const [selectedDebate, setSelectedDebate] = useState<GraphDebate | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedBranch, setHighlightedBranch] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newDebateTask, setNewDebateTask] = useState('');
  const [creating, setCreating] = useState(false);
  const [mobileViewMode, setMobileViewMode] = useState<'graph' | 'list'>('list');
  const isMobile = useIsMobile();

  // WebSocket connection for real-time updates
  const {
    isConnected: wsConnected,
    lastEvent: wsLastEvent,
    status: wsStatus,
    reconnect: wsReconnect,
  } = useGraphDebateWebSocket({ debateId: selectedDebate?.debate_id, enabled: !!selectedDebate });

  // Listen for graph debate events from props
  const latestGraphEvent = useMemo(() => {
    const relevant = events.filter(
      (e) =>
        e.type === 'debate_branch' || e.type === 'debate_merge' || e.type === 'graph_node_added',
    );
    return relevant[relevant.length - 1];
  }, [events]);

  // Refresh debate on WebSocket events
  useEffect(() => {
    if (!wsLastEvent || !selectedDebate) return;

    // Re-fetch the selected debate to get updated graph
    const refreshDebate = async () => {
      try {
        const apiUrl = API_BASE_URL;
        const response = await fetch(`${apiUrl}/api/debates/graph/${selectedDebate.debate_id}`);
        if (response.ok) {
          const data = await response.json();
          setSelectedDebate(data);
          // Also update in list
          setDebates((prev) => prev.map((d) => (d.debate_id === data.debate_id ? data : d)));
        }
      } catch {
        // Ignore refresh errors
      }
    };
    refreshDebate();
  }, [wsLastEvent, selectedDebate]);

  // Refresh on graph events from props (fallback)
  useEffect(() => {
    if (latestGraphEvent && selectedDebate) {
      // Re-fetch the selected debate to get updated graph
      const refreshDebate = async () => {
        try {
          const apiUrl = API_BASE_URL;
          const response = await fetch(`${apiUrl}/api/debates/graph/${selectedDebate.debate_id}`);
          if (response.ok) {
            const data = await response.json();
            setSelectedDebate(data);
            // Also update in list
            setDebates((prev) => prev.map((d) => (d.debate_id === data.debate_id ? data : d)));
          }
        } catch {
          // Ignore refresh errors
        }
      };
      refreshDebate();
    }
  }, [latestGraphEvent, selectedDebate]);

  const fetchDebates = useCallback(async () => {
    try {
      setLoading(true);
      const apiUrl = API_BASE_URL;
      const response = await fetch(`${apiUrl}/api/debates/graph`);
      if (!response.ok) {
        throw new Error(`Failed to fetch graph debates (${response.status})`);
      }
      const data = await response.json();
      const fetchedDebates: GraphDebate[] = Array.isArray(data?.debates)
        ? (data.debates as GraphDebate[])
        : [];
      setDebates(fetchedDebates);
      if (!initialDebateId) {
        setSelectedDebate((current) => {
          if (fetchedDebates.length === 0) {
            return null;
          }

          if (current) {
            return (
              fetchedDebates.find((debate) => debate.debate_id === current.debate_id) ??
              fetchedDebates[0]
            );
          }

          return fetchedDebates[0];
        });
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch graph debates');
    } finally {
      setLoading(false);
    }
  }, [initialDebateId]);

  useEffect(() => {
    fetchDebates();
  }, [fetchDebates]);

  // Auto-fetch and select debate when initialDebateId is provided
  useEffect(() => {
    if (!initialDebateId) return;

    const fetchInitialDebate = async () => {
      try {
        setLoading(true);
        const apiUrl = API_BASE_URL;
        const response = await fetch(`${apiUrl}/api/debates/graph/${initialDebateId}`);
        if (response.ok) {
          const data = await response.json();
          setSelectedDebate(data);
          // Add to debates list if not already present
          setDebates((prev) => {
            const exists = prev.some((d) => d.debate_id === data.debate_id);
            return exists ? prev : [data, ...prev];
          });
        } else {
          setError(`Failed to load debate: ${initialDebateId}`);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load debate');
      } finally {
        setLoading(false);
      }
    };

    fetchInitialDebate();
  }, [initialDebateId]);

  const handleCreateDebate = async () => {
    if (!newDebateTask.trim()) return;

    try {
      setCreating(true);
      const apiUrl = API_BASE_URL;
      const response = await fetch(`${apiUrl}/api/debates/graph`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: newDebateTask, agents: ['claude', 'gpt4'], max_rounds: 5 }),
      });

      if (!response.ok) {
        throw new Error('Failed to create graph debate');
      }

      const data = await response.json();
      setDebates((prev) => [data, ...prev]);
      setSelectedDebate(data);
      setNewDebateTask('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create debate');
    } finally {
      setCreating(false);
    }
  };

  const selectedNode =
    selectedDebate && selectedNodeId ? selectedDebate.graph.nodes[selectedNodeId] : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-theme-data text-[var(--accent)]">{'>'} GRAPH DEBATES</h2>
            {/* WebSocket Status Indicator */}
            {selectedDebate && (
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    wsConnected
                      ? 'bg-[var(--accent)] animate-pulse'
                      : wsStatus === 'connecting'
                        ? 'bg-gold animate-pulse'
                        : 'bg-[var(--crimson)]'
                  }`}
                />
                <span className="text-[10px] font-theme-data text-text-muted">
                  {wsConnected ? 'LIVE' : wsStatus === 'connecting' ? 'CONNECTING' : 'OFFLINE'}
                </span>
                {!wsConnected && wsStatus !== 'connecting' && (
                  <button
                    onClick={wsReconnect}
                    className="text-[10px] font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)]"
                  >
                    [RECONNECT]
                  </button>
                )}
              </div>
            )}
          </div>
          <span className="text-xs font-theme-data text-text-muted">
            Branching & counterfactual exploration
          </span>
        </div>

        {/* Create new debate */}
        <div className="flex gap-2">
          <input
            type="text"
            value={newDebateTask}
            onChange={(e) => setNewDebateTask(e.target.value)}
            placeholder="Enter a topic for graph debate..."
            className="flex-1 px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            onKeyDown={(e) => e.key === 'Enter' && handleCreateDebate()}
          />
          <button
            onClick={handleCreateDebate}
            disabled={creating || !newDebateTask.trim()}
            className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
          >
            {creating ? 'CREATING...' : 'CREATE'}
          </button>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="bg-surface border border-[var(--crimson)]/30 p-4">
          <div className="text-xs font-theme-data text-[var(--crimson)]">Error: {error}</div>
        </div>
      )}

      {/* Main content */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Debate list */}
        <div className="lg:col-span-1 bg-surface border border-[var(--accent)]/30">
          <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
              {'>'} DEBATES ({debates.length})
            </span>
          </div>

          <div className="max-h-[400px] overflow-y-auto">
            {loading && (
              <div className="p-4 space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="p-3 border-b border-border">
                    <Skeleton width="70%" height={14} className="mb-2" />
                    <div className="flex items-center gap-2">
                      <Skeleton width={60} height={10} />
                      <Skeleton width={60} height={10} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!loading && debates.length === 0 && (
              <div className="p-4 text-xs font-theme-data text-text-muted">
                No graph debates yet. Create one above!
              </div>
            )}

            {debates.map((debate) => (
              <button
                key={debate.debate_id}
                data-testid={`graph-debate-item-${debate.debate_id}`}
                onClick={() => {
                  setSelectedDebate(debate);
                  setSelectedNodeId(null);
                }}
                aria-pressed={selectedDebate?.debate_id === debate.debate_id}
                className={`w-full text-left p-3 border-b border-border cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-acid-green/50 ${
                  selectedDebate?.debate_id === debate.debate_id
                    ? 'bg-[var(--accent)]/10 border-l-2 border-l-acid-green'
                    : 'hover:bg-bg'
                }`}
              >
                <div className="text-sm font-theme-data text-text mb-1 truncate">
                  {debate.task.slice(0, 50)}
                  {debate.task.length > 50 ? '...' : ''}
                </div>
                <div className="flex items-center gap-2 text-xs font-theme-data text-text-muted">
                  <span className="text-[var(--accent)]">{debate.node_count} nodes</span>
                  <span>/</span>
                  <span className="text-[var(--acid-cyan)]">{debate.branch_count} branches</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Graph visualization */}
        <div className="lg:col-span-3 bg-surface border border-[var(--accent)]/30 relative min-h-[300px] md:min-h-[500px]">
          <div className="px-3 md:px-4 py-2 md:py-3 border-b border-[var(--accent)]/20 bg-bg/50">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
                  {'>'} GRAPH
                </span>
                {selectedDebate && (
                  <span
                    data-testid="graph-debate-title"
                    className="hidden sm:inline text-xs font-theme-data text-text-muted truncate max-w-[200px] md:max-w-none"
                  >
                    {selectedDebate.task.slice(0, 60)}
                    {selectedDebate.task.length > 60 ? '...' : ''}
                  </span>
                )}
              </div>
              {/* Mobile view toggle */}
              {isMobile && selectedDebate && (
                <div className="flex gap-1" role="group" aria-label="View mode">
                  <button
                    onClick={() => setMobileViewMode('list')}
                    aria-pressed={mobileViewMode === 'list'}
                    className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                      mobileViewMode === 'list'
                        ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-border text-text-muted'
                    }`}
                  >
                    LIST
                  </button>
                  <button
                    onClick={() => setMobileViewMode('graph')}
                    aria-pressed={mobileViewMode === 'graph'}
                    className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                      mobileViewMode === 'graph'
                        ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-border text-text-muted'
                    }`}
                  >
                    GRAPH
                  </button>
                </div>
              )}
            </div>
          </div>

          {selectedDebate ? (
            <>
              {/* Mobile list view */}
              {isMobile && mobileViewMode === 'list' ? (
                <div className="max-h-[400px] overflow-y-auto">
                  <MobileGraphListView
                    nodes={selectedDebate.graph.nodes}
                    selectedNodeId={selectedNodeId}
                    onNodeSelect={setSelectedNodeId}
                  />
                </div>
              ) : (
                /* Graph view - scrollable on mobile */
                <div className="relative w-full overflow-x-auto">
                  <div className="min-w-[600px] lg:min-w-0 p-2 md:p-4">
                    <GraphVisualization
                      graph={selectedDebate.graph}
                      selectedNodeId={selectedNodeId}
                      onNodeSelect={setSelectedNodeId}
                      highlightedBranch={highlightedBranch}
                      onBranchHover={setHighlightedBranch}
                    />
                  </div>
                </div>
              )}

              {/* Branch legend - interactive */}
              <div className="px-4 py-2 border-t border-[var(--accent)]/20 bg-bg/30">
                <div
                  className="flex flex-wrap gap-3 text-xs font-theme-data"
                  role="group"
                  aria-label="Branch filters"
                >
                  {Object.entries(selectedDebate.graph.branches).map(([id, branch]) => (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={highlightedBranch === branch.name}
                      className={`flex items-center gap-1 cursor-pointer px-2 py-1 rounded transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-acid-green/50 ${
                        highlightedBranch === branch.name
                          ? 'bg-[var(--accent)]/20 scale-105'
                          : highlightedBranch && highlightedBranch !== branch.name
                            ? 'opacity-40'
                            : 'hover:bg-surface'
                      }`}
                      onMouseEnter={() => setHighlightedBranch(branch.name)}
                      onMouseLeave={() => setHighlightedBranch(null)}
                      onFocus={() => setHighlightedBranch(branch.name)}
                      onBlur={() => setHighlightedBranch(null)}
                    >
                      <div
                        className={`w-3 h-3 rounded-full ${getBranchBgColor(branch.name)} ${
                          highlightedBranch === branch.name ? 'ring-2 ring-white/50' : ''
                        }`}
                      />
                      <span className={getBranchColor(branch.name)}>{branch.name}</span>
                      <span className="text-text-muted">({branch.node_count} nodes)</span>
                      {branch.is_merged && <span className="text-gold">[merged]</span>}
                      {branch.is_active && (
                        <span className="text-[var(--accent)] animate-pulse">[active]</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {/* Node detail panel */}
              {selectedNode && (
                <NodeDetailPanel node={selectedNode} onClose={() => setSelectedNodeId(null)} />
              )}
            </>
          ) : (
            <div className="flex items-center justify-center h-[400px]">
              <div className="text-center">
                <div className="text-4xl font-theme-data text-[var(--accent)]/30 mb-4">/\</div>
                <div className="text-sm font-theme-data text-text-muted">
                  Select or create a graph debate to visualize
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Merge history */}
      {selectedDebate && selectedDebate.merge_results.length > 0 && (
        <div className="bg-surface border border-purple/30">
          <div className="px-4 py-3 border-b border-purple/20 bg-bg/50">
            <span className="text-xs font-theme-data text-purple uppercase tracking-wider">
              {'>'} MERGE HISTORY ({selectedDebate.merge_results.length})
            </span>
          </div>
          <div className="p-4 space-y-3">
            {selectedDebate.merge_results.map((merge, i) => (
              <div key={i} className="p-3 bg-bg/50 border border-purple/20">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-theme-data text-purple">
                    Merged: {merge.source_branch_ids.join(' + ')}
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    Strategy: {merge.strategy}
                  </span>
                  <span className="text-xs font-theme-data text-[var(--accent)]">
                    {(merge.confidence * 100).toFixed(0)}% confidence
                  </span>
                </div>
                <div className="text-xs font-theme-data text-text">
                  {merge.synthesis.slice(0, 200)}
                  {merge.synthesis.length > 200 ? '...' : ''}
                </div>
                {merge.insights_preserved.length > 0 && (
                  <div className="mt-2 text-[10px] font-theme-data text-text-muted">
                    Preserved: {merge.insights_preserved.slice(0, 3).join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Re-export types and sub-components for external use
export type { GraphDebate, DebateNode, Branch, MergeResult, NodePosition } from './types';
export { GraphVisualization } from './GraphVisualization';
export { GraphNode } from './GraphNode';
export { NodeDetailPanel } from './NodeDetailPanel';
export { MobileGraphListView } from './MobileGraphListView';

export default GraphDebateBrowser;
