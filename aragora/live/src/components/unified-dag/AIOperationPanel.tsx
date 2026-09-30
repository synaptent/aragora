'use client';

import type { DAGOperationResult } from '@/hooks/useUnifiedDAG';

interface AIOperationPanelProps {
  loading: boolean;
  error: string | null;
  result: DAGOperationResult | null;
  onDismiss: () => void;
}

export function AIOperationPanel({ loading, error, result, onDismiss }: AIOperationPanelProps) {
  if (!loading && !error && !result) return null;

  return (
    <aside className="w-80 h-full border-l border-border bg-surface flex-shrink-0 overflow-y-auto">
      <div className="p-4 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-theme-data font-bold text-text uppercase tracking-wide">
            AI Operation
          </h3>
          <button
            onClick={onDismiss}
            className="text-text-muted hover:text-text text-xs font-theme-data"
          >
            {'\u00D7'}
          </button>
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex items-center gap-2 text-indigo-400">
            <div className="w-4 h-4 border-2 border-indigo-400/30 border-t-indigo-400 rounded-full animate-spin" />
            <span className="text-sm font-theme-data">Processing...</span>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="p-3 rounded bg-red-500/10 border border-red-500/30">
            <p className="text-sm font-theme-data text-red-400">{error}</p>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="space-y-3">
            <div
              className={`p-3 rounded border ${
                result.success
                  ? 'bg-emerald-500/10 border-emerald-500/30'
                  : 'bg-red-500/10 border-red-500/30'
              }`}
            >
              <p
                className={`text-sm font-theme-data ${result.success ? 'text-emerald-400' : 'text-red-400'}`}
              >
                {result.message}
              </p>
            </div>

            {/* Created nodes */}
            {result.created_nodes.length > 0 && (
              <div>
                <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider mb-1">
                  Created Nodes
                </h4>
                <div className="space-y-1">
                  {result.created_nodes.map((nodeId) => (
                    <div
                      key={nodeId}
                      className="px-2 py-1 text-xs font-theme-data bg-bg rounded text-text-muted"
                    >
                      {nodeId}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Metadata */}
            {Object.keys(result.metadata).length > 0 && (
              <div>
                <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider mb-1">
                  Details
                </h4>
                <pre className="text-xs font-theme-data text-text-muted bg-bg p-2 rounded overflow-x-auto max-h-48">
                  {JSON.stringify(result.metadata, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
