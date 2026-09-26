'use client';

import { useCallback } from 'react';
import { GOAL_NODE_CONFIGS, type GoalNodeType, type GoalTypeConfig } from './types';

const groups: { label: string; key: GoalTypeConfig['group']; types: GoalNodeType[] }[] = [
  { label: 'Objectives', key: 'Objectives', types: ['goal', 'principle'] },
  { label: 'Strategy', key: 'Strategy', types: ['strategy', 'milestone'] },
  { label: 'Tracking', key: 'Tracking', types: ['metric', 'risk'] },
];

/**
 * Drag-and-drop palette for adding goal nodes to the canvas.
 */
export function GoalPalette() {
  const onDragStart = useCallback((e: React.DragEvent, goalType: GoalNodeType) => {
    e.dataTransfer.setData('application/goal-node-type', goalType);
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  return (
    <div className="w-48 border-r border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
      <h3 className="text-xs font-theme-data uppercase text-text-muted mb-3 tracking-wider">
        Goal Types
      </h3>
      {groups.map((group) => (
        <div key={group.key} className="mb-4">
          <div className="text-xs font-theme-data text-text-muted mb-2 uppercase tracking-wide">
            {group.label}
          </div>
          <div className="space-y-1.5">
            {group.types.map((goalType) => {
              const config = GOAL_NODE_CONFIGS[goalType];
              return (
                <div
                  key={goalType}
                  draggable
                  onDragStart={(e) => onDragStart(e, goalType)}
                  className={`
                    flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-grab
                    border border-transparent hover:border-[var(--border)]
                    ${config.color} transition-colors
                  `}
                  title={config.description}
                >
                  <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-emerald-500/30 text-emerald-200">
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

export default GoalPalette;
