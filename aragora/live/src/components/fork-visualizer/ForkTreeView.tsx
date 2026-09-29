'use client';

import { type ForkNode, type ForkTree } from '@/hooks/useDebateFork';

interface ForkTreeViewProps {
  tree: ForkTree | null;
  onNodeSelect: (node: ForkNode) => void;
  onCompareSelect: (node: ForkNode, slot: 0 | 1) => void;
  selectedNodes: [ForkNode | null, ForkNode | null];
}

function TreeNode({
  node,
  depth,
  onNodeSelect,
  onCompareSelect,
  selectedNodes,
}: {
  node: ForkNode;
  depth: number;
  onNodeSelect: (node: ForkNode) => void;
  onCompareSelect: (node: ForkNode, slot: 0 | 1) => void;
  selectedNodes: [ForkNode | null, ForkNode | null];
}) {
  const isSelected = selectedNodes.some((s) => s?.id === node.id);
  const selectedSlot =
    selectedNodes[0]?.id === node.id ? 0 : selectedNodes[1]?.id === node.id ? 1 : null;

  const statusColor =
    {
      created: 'bg-[var(--acid-cyan)]',
      running: 'bg-acid-yellow animate-pulse',
      completed: 'bg-[var(--accent)]',
      unknown: 'bg-text-muted',
    }[node.status || 'unknown'] || 'bg-text-muted';

  return (
    <div className="ml-4">
      <div
        className={`flex items-center gap-2 p-2 rounded cursor-pointer transition-colors ${isSelected ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/30' : 'hover:bg-surface/50'}`}
        onClick={() => onNodeSelect(node)}
      >
        <div className={`w-3 h-3 rounded-full ${statusColor}`} />
        <div className="flex-1">
          <div className="text-xs font-theme-data text-text">
            {node.type === 'root' ? 'ROOT' : `Fork @ R${node.branch_point}`}
          </div>
          {node.pivot_claim && (
            <div
              className="text-[10px] font-theme-data text-text-muted truncate max-w-48"
              title={node.pivot_claim}
            >
              {node.pivot_claim}
            </div>
          )}
        </div>
        <div className="flex gap-1">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onCompareSelect(node, 0);
            }}
            className={`px-1.5 py-0.5 text-[10px] font-theme-data border transition-colors ${selectedSlot === 0 ? 'border-[var(--acid-cyan)] text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10' : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'}`}
          >
            L
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onCompareSelect(node, 1);
            }}
            className={`px-1.5 py-0.5 text-[10px] font-theme-data border transition-colors ${selectedSlot === 1 ? 'border-[var(--acid-cyan)] text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10' : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'}`}
          >
            R
          </button>
        </div>
      </div>
      {node.children && node.children.length > 0 && (
        <div className="border-l border-[var(--accent)]/20 ml-1.5">
          {node.children.map((child, idx) => (
            <TreeNode
              key={child.id || idx}
              node={child}
              depth={depth + 1}
              onNodeSelect={onNodeSelect}
              onCompareSelect={onCompareSelect}
              selectedNodes={selectedNodes}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function ForkTreeView({
  tree,
  onNodeSelect,
  onCompareSelect,
  selectedNodes,
}: ForkTreeViewProps) {
  if (!tree) {
    return (
      <div className="text-center py-8 text-xs font-theme-data text-text-muted">
        No fork tree available
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs font-theme-data text-text-muted">
          {tree.total_nodes} nodes | max depth: {tree.max_depth}
        </div>
        <div className="flex items-center gap-3 text-[10px] font-theme-data text-text-muted">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[var(--accent)]" /> completed
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-acid-yellow" /> running
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[var(--acid-cyan)]" /> created
          </span>
        </div>
      </div>
      <TreeNode
        node={tree as ForkNode}
        depth={0}
        onNodeSelect={onNodeSelect}
        onCompareSelect={onCompareSelect}
        selectedNodes={selectedNodes}
      />
    </div>
  );
}
