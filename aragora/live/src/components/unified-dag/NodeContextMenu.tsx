'use client';

import type { DAGStage } from '@/hooks/useUnifiedDAG';

interface NodeContextMenuProps {
  nodeId: string;
  stage: DAGStage;
  x: number;
  y: number;
  onClose: () => void;
  onDebate: (nodeId: string) => void;
  onDecompose: (nodeId: string) => void;
  onPrioritize: (nodeId: string) => void;
  onAssignAgents: (nodeId: string) => void;
  onExecute: (nodeId: string) => void;
  onFindPrecedents: (nodeId: string) => void;
  onDelete: (nodeId: string) => void;
  onValidate?: (nodeId: string) => void;
  onEnrich?: (nodeId: string) => void;
  onImprove?: (nodeId: string) => void;
}

interface MenuItem {
  label: string;
  icon: string;
  action: () => void;
  stages: DAGStage[];
}

export function NodeContextMenu({
  nodeId,
  stage,
  x,
  y,
  onClose,
  onDebate,
  onDecompose,
  onPrioritize,
  onAssignAgents,
  onExecute,
  onFindPrecedents,
  onDelete,
  onValidate,
  onEnrich,
  onImprove,
}: NodeContextMenuProps) {
  const items: MenuItem[] = [
    {
      label: 'Debate',
      icon: '\u2694',
      action: () => {
        onDebate(nodeId);
        onClose();
      },
      stages: ['ideas', 'principles', 'goals'],
    },
    {
      label: 'Decompose',
      icon: '\u2702',
      action: () => {
        onDecompose(nodeId);
        onClose();
      },
      stages: ['ideas', 'goals'],
    },
    {
      label: 'Prioritize',
      icon: '\u2195',
      action: () => {
        onPrioritize(nodeId);
        onClose();
      },
      stages: ['goals', 'actions'],
    },
    {
      label: 'Assign Agents',
      icon: '\u{1F464}',
      action: () => {
        onAssignAgents(nodeId);
        onClose();
      },
      stages: ['actions', 'orchestration'],
    },
    {
      label: 'Execute',
      icon: '\u25B6',
      action: () => {
        onExecute(nodeId);
        onClose();
      },
      stages: ['actions', 'orchestration'],
    },
    {
      label: 'Find Precedents',
      icon: '\u{1F50D}',
      action: () => {
        onFindPrecedents(nodeId);
        onClose();
      },
      stages: ['ideas', 'principles', 'goals', 'actions', 'orchestration'],
    },
    {
      label: 'Validate',
      icon: '\u{1F6E1}',
      action: () => {
        onValidate?.(nodeId);
        onClose();
      },
      stages: ['goals', 'actions'],
    },
    {
      label: 'Enrich with Knowledge',
      icon: '\u{1F4DA}',
      action: () => {
        onEnrich?.(nodeId);
        onClose();
      },
      stages: ['ideas', 'principles', 'goals', 'actions', 'orchestration'],
    },
    {
      label: 'Improve This',
      icon: '\u2728',
      action: () => {
        onImprove?.(nodeId);
        onClose();
      },
      stages: ['ideas', 'principles', 'goals', 'actions', 'orchestration'],
    },
    {
      label: 'Delete',
      icon: '\u{1F5D1}',
      action: () => {
        onDelete(nodeId);
        onClose();
      },
      stages: ['ideas', 'principles', 'goals', 'actions', 'orchestration'],
    },
  ];

  const visibleItems = items.filter((item) => item.stages.includes(stage));

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40" onClick={onClose} />
      {/* Menu */}
      <div
        className="fixed z-50 min-w-[180px] bg-surface border border-border rounded-lg shadow-xl py-1 font-theme-data text-sm"
        style={{ left: x, top: y }}
      >
        {visibleItems.map((item) => (
          <button
            key={item.label}
            onClick={item.action}
            className="w-full text-left px-3 py-2 hover:bg-indigo-600/20 text-text flex items-center gap-2 transition-colors"
          >
            <span className="text-base">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </>
  );
}
