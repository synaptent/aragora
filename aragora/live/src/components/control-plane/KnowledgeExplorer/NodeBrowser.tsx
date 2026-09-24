'use client';

import { useCallback } from 'react';
import type { KnowledgeNode, NodeType, MemoryTier } from '@/store/knowledgeExplorerStore';

export interface NodeBrowserProps {
  /** List of nodes to display */
  nodes: KnowledgeNode[];
  /** Currently selected node ID */
  selectedNodeId?: string | null;
  /** Callback when a node is selected */
  onSelectNode?: (node: KnowledgeNode) => void;
  /** Callback to view in graph */
  onViewInGraph?: (node: KnowledgeNode) => void;
  /** Loading state */
  loading?: boolean;
  /** Empty message */
  emptyMessage?: string;
}

const nodeTypeIcons: Record<NodeType, string> = {
  fact: '📋',
  claim: '💭',
  memory: '🧠',
  evidence: '📎',
  consensus: '🤝',
  entity: '🏷️',
};

const nodeTypeColors: Record<NodeType, string> = {
  fact: 'text-green-400',
  claim: 'text-blue-400',
  memory: 'text-purple-400',
  evidence: 'text-yellow-400',
  consensus: 'text-[var(--acid-cyan)]',
  entity: 'text-orange-400',
};

const tierColors: Record<MemoryTier, string> = {
  fast: 'bg-red-400',
  medium: 'bg-yellow-400',
  slow: 'bg-blue-400',
  glacial: 'bg-purple-400',
};

/**
 * Browser component for viewing knowledge nodes in a list.
 */
export function NodeBrowser({
  nodes,
  selectedNodeId,
  onSelectNode,
  onViewInGraph,
  loading = false,
  emptyMessage = 'No knowledge nodes found',
}: NodeBrowserProps) {
  const handleNodeClick = useCallback(
    (node: KnowledgeNode) => {
      onSelectNode?.(node);
    },
    [onSelectNode],
  );

  const handleViewInGraph = useCallback(
    (e: React.MouseEvent, node: KnowledgeNode) => {
      e.stopPropagation();
      onViewInGraph?.(node);
    },
    [onViewInGraph],
  );

  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse">
            <div className="h-20 bg-surface rounded-lg" />
          </div>
        ))}
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="text-center py-8 text-text-muted">
        <div className="text-4xl mb-2">📭</div>
        <p>{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {nodes.map((node) => (
        <div
          key={node.id}
          onClick={() => handleNodeClick(node)}
          className={`
            p-3 rounded-lg border cursor-pointer transition-all
            ${
              selectedNodeId === node.id
                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-border hover:border-text-muted hover:bg-surface/50'
            }
          `}
        >
          {/* Header */}
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              {/* Node type icon */}
              <span className={nodeTypeColors[node.node_type]}>
                {nodeTypeIcons[node.node_type]}
              </span>

              {/* Node type label */}
              <span
                className={`text-xs font-theme-data uppercase ${nodeTypeColors[node.node_type]}`}
              >
                {node.node_type}
              </span>

              {/* Tier indicator */}
              <div
                className={`w-2 h-2 rounded-full ${tierColors[node.tier]}`}
                title={`${node.tier} tier`}
              />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-1">
              {onViewInGraph && (
                <button
                  onClick={(e) => handleViewInGraph(e, node)}
                  className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors p-1"
                  title="View in graph"
                >
                  🔗
                </button>
              )}
            </div>
          </div>

          {/* Content preview */}
          <p className="text-sm text-text line-clamp-2 mb-2">{node.content}</p>

          {/* Footer */}
          <div className="flex items-center justify-between text-xs">
            {/* Confidence */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1">
                <span className="text-text-muted">Confidence:</span>
                <span
                  className={`font-theme-data ${
                    node.confidence >= 0.8
                      ? 'text-green-400'
                      : node.confidence >= 0.5
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }`}
                >
                  {Math.round(node.confidence * 100)}%
                </span>
              </div>

              {/* Staleness */}
              {node.staleness_score !== undefined && node.staleness_score > 0.3 && (
                <div className="flex items-center gap-1 text-yellow-400">
                  <span>⚠</span>
                  <span>Stale</span>
                </div>
              )}
            </div>

            {/* Timestamp */}
            <span className="text-text-muted">
              {new Date(node.created_at).toLocaleDateString()}
            </span>
          </div>

          {/* Topics */}
          {node.topics && node.topics.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {node.topics.slice(0, 4).map((topic) => (
                <span
                  key={topic}
                  className="px-1.5 py-0.5 text-xs bg-surface rounded text-text-muted"
                >
                  {topic}
                </span>
              ))}
              {node.topics.length > 4 && (
                <span className="px-1.5 py-0.5 text-xs text-text-muted">
                  +{node.topics.length - 4}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default NodeBrowser;
