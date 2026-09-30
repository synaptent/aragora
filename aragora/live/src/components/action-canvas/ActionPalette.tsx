'use client';

import { useCallback } from 'react';
import { ACTION_NODE_CONFIGS, type ActionNodeType, type ActionTypeConfig } from './types';

const groups: { label: string; key: ActionTypeConfig['group']; types: ActionNodeType[] }[] = [
  { label: 'Execution', key: 'Execution', types: ['task', 'epic'] },
  { label: 'Verification', key: 'Verification', types: ['checkpoint'] },
  { label: 'Management', key: 'Management', types: ['deliverable', 'dependency'] },
];

export function ActionPalette() {
  const onDragStart = useCallback((e: React.DragEvent, actionType: ActionNodeType) => {
    e.dataTransfer.setData('application/action-node-type', actionType);
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  return (
    <div className="w-48 border-r border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
      <h3 className="text-xs font-theme-data uppercase text-text-muted mb-3 tracking-wider">
        Action Types
      </h3>
      {groups.map((group) => (
        <div key={group.key} className="mb-4">
          <div className="text-xs font-theme-data text-text-muted mb-2 uppercase tracking-wide">
            {group.label}
          </div>
          <div className="space-y-1.5">
            {group.types.map((actionType) => {
              const config = ACTION_NODE_CONFIGS[actionType];
              return (
                <div
                  key={actionType}
                  draggable
                  onDragStart={(e) => onDragStart(e, actionType)}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-grab border border-transparent hover:border-[var(--border)] ${config.color} transition-colors`}
                  title={config.description}
                >
                  <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-amber-500/30 text-amber-200">
                    {config.icon}
                  </span>
                  <span className="text-xs text-text">{config.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export default ActionPalette;
