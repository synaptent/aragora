'use client';

import { getAgentColors } from '@/utils/agentColors';
import type { DebateNode } from './types';
import { getBranchColor } from './utils';

export interface MobileGraphListViewProps {
  nodes: Record<string, DebateNode>;
  selectedNodeId: string | null;
  onNodeSelect: (nodeId: string | null) => void;
}

/**
 * Mobile list view for graph debates (fallback for small screens).
 */
export function MobileGraphListView({
  nodes,
  selectedNodeId,
  onNodeSelect,
}: MobileGraphListViewProps) {
  // Sort nodes by timestamp
  const sortedNodes = Object.values(nodes).sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );

  return (
    <div className="space-y-2 p-2">
      <div className="text-xs font-theme-data text-text-muted mb-3 px-2">
        Showing {sortedNodes.length} nodes (tap for details)
      </div>
      {sortedNodes.map((node) => {
        const colors = getAgentColors(node.agent_id);
        const isSelected = selectedNodeId === node.id;

        return (
          <button
            key={node.id}
            onClick={() => onNodeSelect(isSelected ? null : node.id)}
            className={`w-full text-left p-3 border transition-all ${
              isSelected
                ? 'bg-[var(--accent)]/10 border-[var(--accent)]'
                : 'bg-bg border-border hover:border-[var(--accent)]/50'
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span
                  className={`px-1.5 py-0.5 text-xs font-theme-data ${colors.bg} ${colors.text}`}
                >
                  {node.agent_id.slice(0, 8)}
                </span>
                <span
                  className={`text-xs font-theme-data ${getBranchColor(node.branch_id || 'main')}`}
                >
                  {node.node_type.replace('_', ' ')}
                </span>
              </div>
              <span className="text-xs font-theme-data text-[var(--accent)]">
                {(node.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="text-xs font-theme-data text-text-muted line-clamp-2">
              {node.content.slice(0, 150)}
              {node.content.length > 150 ? '...' : ''}
            </div>
            {isSelected && (
              <div className="mt-2 pt-2 border-t border-border text-xs font-theme-data text-text">
                {node.content}
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default MobileGraphListView;
