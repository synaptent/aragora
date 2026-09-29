'use client';

/**
 * Stale Knowledge Tab Component
 *
 * Displays knowledge nodes that need revalidation, allowing users to
 * view, revalidate, or dismiss stale knowledge entries.
 */

import { useState, useCallback, useMemo } from 'react';

export interface StaleNode {
  id: string;
  content: string;
  node_type: string;
  confidence: number;
  staleReason: string;
  lastValidated?: string;
  daysStale: number;
}

interface StaleKnowledgeTabProps {
  nodes: StaleNode[];
  loading?: boolean;
  onRevalidate?: (nodeId: string) => Promise<void>;
  onScheduleRevalidation?: (nodeIds: string[]) => Promise<void>;
  onDismiss?: (nodeId: string) => void;
  onRefresh?: () => void;
}

const STALE_REASONS: Record<string, string> = {
  age: 'Age threshold exceeded',
  dependency_changed: 'Dependency changed',
  source_updated: 'Source document updated',
  confidence_decay: 'Confidence decayed over time',
  manual_flag: 'Manually flagged for review',
};

export function StaleKnowledgeTab({
  nodes,
  loading = false,
  onRevalidate,
  onScheduleRevalidation,
  onDismiss,
  onRefresh,
}: StaleKnowledgeTabProps) {
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set());
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [sortBy, setSortBy] = useState<'daysStale' | 'confidence'>('daysStale');

  // Sort nodes
  const sortedNodes = useMemo(() => {
    return [...nodes].sort((a, b) => {
      if (sortBy === 'daysStale') {
        return b.daysStale - a.daysStale;
      }
      return a.confidence - b.confidence;
    });
  }, [nodes, sortBy]);

  // Handle node selection
  const toggleNodeSelection = useCallback((nodeId: string) => {
    setSelectedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  // Handle select all
  const toggleSelectAll = useCallback(() => {
    if (selectedNodes.size === nodes.length) {
      setSelectedNodes(new Set());
    } else {
      setSelectedNodes(new Set(nodes.map((n) => n.id)));
    }
  }, [nodes, selectedNodes.size]);

  // Handle revalidate single
  const handleRevalidate = useCallback(
    async (nodeId: string) => {
      if (!onRevalidate) return;
      setActionLoading(nodeId);
      try {
        await onRevalidate(nodeId);
      } finally {
        setActionLoading(null);
      }
    },
    [onRevalidate],
  );

  // Handle bulk revalidation
  const handleBulkRevalidate = useCallback(async () => {
    if (!onScheduleRevalidation || selectedNodes.size === 0) return;
    setBulkLoading(true);
    try {
      await onScheduleRevalidation(Array.from(selectedNodes));
      setSelectedNodes(new Set());
    } finally {
      setBulkLoading(false);
    }
  }, [onScheduleRevalidation, selectedNodes]);

  // Get staleness severity color
  const getStaleColor = (days: number) => {
    if (days > 30) return 'text-red-400';
    if (days > 14) return 'text-orange-400';
    if (days > 7) return 'text-yellow-400';
    return 'text-text-muted';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full mx-auto" />
          <p className="text-sm text-text-muted mt-4">Loading stale knowledge...</p>
        </div>
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="text-center py-12">
        <span className="text-4xl">✅</span>
        <h4 className="font-theme-data font-bold text-text mt-4">All Knowledge Current</h4>
        <p className="text-sm text-text-muted mt-2">No stale knowledge nodes need revalidation</p>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="mt-4 px-4 py-2 text-xs font-theme-data bg-bg border border-border rounded hover:border-[var(--accent)] transition-colors"
          >
            CHECK AGAIN
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header Actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={selectedNodes.size === nodes.length}
              onChange={toggleSelectAll}
              className="w-4 h-4 rounded border-border bg-bg accent-acid-green"
            />
            <span className="text-xs text-text-muted">
              {selectedNodes.size > 0 ? `${selectedNodes.size} selected` : 'Select all'}
            </span>
          </label>

          {selectedNodes.size > 0 && onScheduleRevalidation && (
            <button
              onClick={handleBulkRevalidate}
              disabled={bulkLoading}
              className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {bulkLoading ? '...' : `REVALIDATE (${selectedNodes.size})`}
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Sort by:</span>
          <button
            onClick={() => setSortBy('daysStale')}
            className={`px-2 py-1 text-xs font-theme-data rounded ${
              sortBy === 'daysStale'
                ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'bg-bg border border-border'
            }`}
          >
            AGE
          </button>
          <button
            onClick={() => setSortBy('confidence')}
            className={`px-2 py-1 text-xs font-theme-data rounded ${
              sortBy === 'confidence'
                ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'bg-bg border border-border'
            }`}
          >
            CONFIDENCE
          </button>
        </div>
      </div>

      {/* Node List */}
      <div className="space-y-2">
        {sortedNodes.map((node) => (
          <div
            key={node.id}
            className={`
              p-4 bg-bg border rounded-lg transition-colors
              ${selectedNodes.has(node.id) ? 'border-[var(--accent)]' : 'border-border'}
            `}
          >
            <div className="flex items-start gap-3">
              {/* Selection Checkbox */}
              <input
                type="checkbox"
                checked={selectedNodes.has(node.id)}
                onChange={() => toggleNodeSelection(node.id)}
                className="mt-1 w-4 h-4 rounded border-border bg-surface accent-acid-green"
              />

              {/* Node Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text line-clamp-2">{node.content}</p>
                    <div className="flex items-center gap-3 mt-2 text-xs">
                      <span className="px-1.5 py-0.5 bg-surface border border-border rounded font-theme-data">
                        {node.node_type}
                      </span>
                      <span className="text-text-muted">
                        {Math.round(node.confidence * 100)}% confidence
                      </span>
                      <span className={getStaleColor(node.daysStale)}>{node.daysStale}d stale</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {onRevalidate && (
                      <button
                        onClick={() => handleRevalidate(node.id)}
                        disabled={actionLoading === node.id}
                        className="px-2 py-1 text-xs font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/10 rounded transition-colors disabled:opacity-50"
                      >
                        {actionLoading === node.id ? '...' : 'REVALIDATE'}
                      </button>
                    )}
                    {onDismiss && (
                      <button
                        onClick={() => onDismiss(node.id)}
                        className="px-2 py-1 text-xs font-theme-data text-text-muted hover:text-text hover:bg-surface rounded transition-colors"
                      >
                        DISMISS
                      </button>
                    )}
                  </div>
                </div>

                {/* Stale Reason */}
                <div className="mt-3 p-2 bg-yellow-500/10 border border-yellow-500/20 rounded">
                  <span className="text-xs text-yellow-400 font-theme-data">
                    Reason: {STALE_REASONS[node.staleReason] || node.staleReason}
                  </span>
                  {node.lastValidated && (
                    <span className="text-xs text-text-muted ml-3">
                      Last validated: {new Date(node.lastValidated).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Summary */}
      <div className="pt-4 border-t border-border">
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>{nodes.length} stale nodes need attention</span>
          {onRefresh && (
            <button onClick={onRefresh} className="text-[var(--accent)] hover:underline">
              Refresh
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default StaleKnowledgeTab;
