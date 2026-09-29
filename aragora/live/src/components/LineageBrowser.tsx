'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

interface LineageNode {
  genome_id: string;
  name?: string;
  generation: number;
  fitness_score?: number;
  parent_ids?: string[];
  created_at?: string;
  event_type?: string;
}

interface LineageData {
  genome_id: string;
  lineage: LineageNode[];
  generations: number;
}

interface LineageBrowserProps {
  genomeId?: string;
  apiBase?: string;
  onGenomeSelect?: (genomeId: string) => void;
  maxDepth?: number;
}

const NODE_COLORS = {
  root: {
    bg: 'bg-[var(--accent)]/20',
    border: 'border-[var(--accent)]',
    text: 'text-[var(--accent)]',
  },
  parent: {
    bg: 'bg-[var(--acid-cyan)]/20',
    border: 'border-[var(--acid-cyan)]',
    text: 'text-[var(--acid-cyan)]',
  },
  ancestor: {
    bg: 'bg-acid-yellow/20',
    border: 'border-acid-yellow',
    text: 'text-[var(--acid-yellow)]',
  },
  origin: { bg: 'bg-accent/20', border: 'border-accent', text: 'text-accent' },
};

function LineageNode({
  node,
  isRoot,
  depth,
  onSelect,
  selectedId,
}: {
  node: LineageNode;
  isRoot: boolean;
  depth: number;
  onSelect?: (id: string) => void;
  selectedId?: string;
}) {
  const colors = isRoot
    ? NODE_COLORS.root
    : depth === 1
      ? NODE_COLORS.parent
      : depth < 4
        ? NODE_COLORS.ancestor
        : NODE_COLORS.origin;

  const isSelected = selectedId === node.genome_id;

  return (
    <button
      onClick={() => onSelect?.(node.genome_id)}
      className={`
        w-full text-left p-3 rounded-lg border-2 transition-all
        ${colors.bg} ${colors.border}
        ${isSelected ? 'ring-2 ring-offset-2 ring-acid-green ring-offset-bg' : ''}
        hover:brightness-110 cursor-pointer
      `}
    >
      <div className="flex items-center justify-between mb-1">
        <span className={`font-theme-data text-xs uppercase ${colors.text}`}>
          {isRoot ? 'CURRENT' : `GEN ${node.generation}`}
        </span>
        {node.fitness_score !== undefined && (
          <span className="text-xs font-theme-data text-[var(--acid-yellow)]">
            {(node.fitness_score * 100).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="font-theme-data text-sm text-text truncate">
        {node.name || node.genome_id.slice(0, 12) + '...'}
      </div>
      {node.event_type && (
        <div className="text-xs font-theme-data text-text-muted mt-1">via {node.event_type}</div>
      )}
    </button>
  );
}

function LineageTree({
  nodes,
  rootId,
  onSelect,
  selectedId,
}: {
  nodes: LineageNode[];
  rootId: string;
  onSelect?: (id: string) => void;
  selectedId?: string;
}) {
  // Build tree structure from flat list
  const nodeMap = useMemo(() => {
    const map = new Map<string, LineageNode>();
    nodes.forEach((n) => map.set(n.genome_id, n));
    return map;
  }, [nodes]);

  // Group nodes by generation
  const generations = useMemo(() => {
    const gens = new Map<number, LineageNode[]>();
    nodes.forEach((node) => {
      const gen = node.generation;
      if (!gens.has(gen)) gens.set(gen, []);
      gens.get(gen)!.push(node);
    });
    return Array.from(gens.entries()).sort((a, b) => b[0] - a[0]);
  }, [nodes]);

  const rootNode = nodeMap.get(rootId);

  if (!rootNode) {
    return (
      <div className="text-text-muted font-theme-data text-sm text-center py-4">
        No lineage data available
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tree visualization */}
      <div className="relative">
        {generations.map(([gen, genNodes], genIdx) => (
          <div key={gen} className="mb-4">
            {/* Generation label */}
            <div className="text-xs font-theme-data text-text-muted mb-2 flex items-center gap-2">
              <span className="w-16">Gen {gen}</span>
              <div className="flex-1 h-px bg-[var(--accent)]/20" />
            </div>

            {/* Nodes at this generation */}
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: `repeat(${Math.min(genNodes.length, 3)}, 1fr)` }}
            >
              {genNodes.map((node) => (
                <div key={node.genome_id} className="relative">
                  <LineageNode
                    node={node}
                    isRoot={node.genome_id === rootId}
                    depth={genIdx}
                    onSelect={onSelect}
                    selectedId={selectedId}
                  />
                  {/* Connection lines to children */}
                  {genIdx > 0 && (
                    <div className="absolute -top-4 left-1/2 w-px h-4 bg-[var(--accent)]/30" />
                  )}
                </div>
              ))}
            </div>

            {/* Vertical connector to next generation */}
            {genIdx < generations.length - 1 && (
              <div className="flex justify-center my-2">
                <div className="w-px h-6 bg-[var(--accent)]/30" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function LineageBrowser({
  genomeId,
  apiBase = API_BASE_URL,
  onGenomeSelect,
  maxDepth = 10,
}: LineageBrowserProps) {
  const [lineage, setLineage] = useState<LineageData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(genomeId);
  const [searchId, setSearchId] = useState(genomeId || '');

  const fetchLineage = useCallback(
    async (id: string) => {
      if (!id) return;

      setLoading(true);
      setError(null);

      try {
        const response = await fetch(`${apiBase}/api/genesis/lineage/${id}?max_depth=${maxDepth}`);
        if (!response.ok) {
          if (response.status === 404) {
            throw new Error('Genome not found');
          }
          const data = await response.json();
          throw new Error(data.error || `HTTP ${response.status}`);
        }
        const data = await response.json();
        setLineage(data);
        setSelectedId(id);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch lineage');
        setLineage(null);
      } finally {
        setLoading(false);
      }
    },
    [apiBase, maxDepth],
  );

  useEffect(() => {
    if (genomeId) {
      fetchLineage(genomeId);
      setSearchId(genomeId);
    }
  }, [genomeId, fetchLineage]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchId.trim()) {
      fetchLineage(searchId.trim());
    }
  };

  const handleNodeSelect = (id: string) => {
    setSelectedId(id);
    if (onGenomeSelect) {
      onGenomeSelect(id);
    }
  };

  const handleNavigateToNode = (id: string) => {
    setSearchId(id);
    fetchLineage(id);
  };

  // Get selected node details
  const selectedNode = lineage?.lineage.find((n) => n.genome_id === selectedId);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="font-theme-data text-[var(--accent)] text-sm">LINEAGE BROWSER</h4>
        {lineage && (
          <div className="text-xs font-theme-data text-text-muted">
            {lineage.generations} generations
          </div>
        )}
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={searchId}
          onChange={(e) => setSearchId(e.target.value)}
          placeholder="Enter genome ID..."
          className="flex-1 bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading || !searchId.trim()}
          className="px-4 py-2 font-theme-data text-xs border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
        >
          {loading ? 'LOADING...' : 'TRACE'}
        </button>
      </form>

      {/* Error */}
      {error && (
        <div className="p-4 bg-warning/10 border border-warning/30 rounded-lg">
          <div className="text-warning font-theme-data text-sm">{error}</div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="p-4 text-center">
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Tracing lineage...
          </div>
        </div>
      )}

      {/* Lineage Tree */}
      {!loading && lineage && (
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Tree visualization */}
          <div className="lg:col-span-2 bg-surface/50 border border-border rounded-lg p-4">
            <LineageTree
              nodes={lineage.lineage}
              rootId={lineage.genome_id}
              onSelect={handleNodeSelect}
              selectedId={selectedId}
            />
          </div>

          {/* Selected node details */}
          <div className="bg-surface border border-[var(--acid-cyan)]/30 rounded-lg p-4">
            <h5 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-4">NODE DETAILS</h5>
            {selectedNode ? (
              <div className="space-y-4">
                <div>
                  <div className="text-xs text-text-muted mb-1">ID</div>
                  <div className="font-theme-data text-xs text-[var(--accent)] break-all">
                    {selectedNode.genome_id}
                  </div>
                </div>

                {selectedNode.name && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">NAME</div>
                    <div className="font-theme-data text-sm text-text">{selectedNode.name}</div>
                  </div>
                )}

                <div>
                  <div className="text-xs text-text-muted mb-1">GENERATION</div>
                  <div className="font-theme-data text-lg text-[var(--acid-cyan)]">
                    {selectedNode.generation}
                  </div>
                </div>

                {selectedNode.fitness_score !== undefined && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">FITNESS</div>
                    <div className="font-theme-data text-lg text-[var(--acid-yellow)]">
                      {(selectedNode.fitness_score * 100).toFixed(2)}%
                    </div>
                  </div>
                )}

                {selectedNode.event_type && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">CREATED VIA</div>
                    <div className="font-theme-data text-sm text-text">
                      {selectedNode.event_type}
                    </div>
                  </div>
                )}

                {selectedNode.created_at && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">CREATED</div>
                    <div className="font-theme-data text-xs text-text-muted">
                      {new Date(selectedNode.created_at).toLocaleString()}
                    </div>
                  </div>
                )}

                {selectedNode.parent_ids && selectedNode.parent_ids.length > 0 && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">PARENTS</div>
                    <div className="space-y-1">
                      {selectedNode.parent_ids.map((pid) => (
                        <button
                          key={pid}
                          onClick={() => handleNavigateToNode(pid)}
                          className="block w-full text-left font-theme-data text-xs text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                        >
                          {pid.slice(0, 16)}... [TRACE]
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Navigate to this genome */}
                {selectedNode.genome_id !== lineage.genome_id && (
                  <button
                    onClick={() => handleNavigateToNode(selectedNode.genome_id)}
                    className="w-full py-2 font-theme-data text-xs border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                  >
                    TRACE FROM THIS NODE
                  </button>
                )}
              </div>
            ) : (
              <div className="text-center text-text-muted font-theme-data text-sm py-8">
                Select a node to view details
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && !lineage && !error && (
        <div className="text-center py-8 border border-[var(--accent)]/20 rounded-lg bg-surface/50">
          <div className="text-text-muted font-theme-data text-sm mb-2">
            Enter a genome ID to trace its evolutionary lineage
          </div>
          <div className="text-xs font-theme-data text-text-muted/50">
            View ancestry, mutations, and crossovers
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs font-theme-data">
        <div className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded ${NODE_COLORS.root.bg} ${NODE_COLORS.root.border} border`}
          />
          <span className="text-text-muted">Current</span>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded ${NODE_COLORS.parent.bg} ${NODE_COLORS.parent.border} border`}
          />
          <span className="text-text-muted">Parent</span>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded ${NODE_COLORS.ancestor.bg} ${NODE_COLORS.ancestor.border} border`}
          />
          <span className="text-text-muted">Ancestor</span>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded ${NODE_COLORS.origin.bg} ${NODE_COLORS.origin.border} border`}
          />
          <span className="text-text-muted">Origin</span>
        </div>
      </div>
    </div>
  );
}

export default LineageBrowser;
