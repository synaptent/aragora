'use client';

import { useCallback } from 'react';
import { ORCH_NODE_CONFIGS, type OrchNodeType, type OrchTypeConfig } from './types';

const groups: { label: string; key: OrchTypeConfig['group']; types: OrchNodeType[] }[] = [
  { label: 'Agents', key: 'Agents', types: ['agent_task', 'debate'] },
  { label: 'Control Flow', key: 'Control Flow', types: ['parallel_fan', 'merge'] },
  { label: 'Gates', key: 'Gates', types: ['human_gate', 'verification'] },
];

export function OrchPalette() {
  const onDragStart = useCallback((e: React.DragEvent, orchType: OrchNodeType) => {
    e.dataTransfer.setData('application/orch-node-type', orchType);
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  return (
    <div className="w-48 border-r border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
      <h3 className="text-xs font-theme-data uppercase text-text-muted mb-3 tracking-wider">
        Orchestration Types
      </h3>
      {groups.map((group) => (
        <div key={group.key} className="mb-4">
          <div className="text-xs font-theme-data text-text-muted mb-2 uppercase tracking-wide">
            {group.label}
          </div>
          <div className="space-y-1.5">
            {group.types.map((orchType) => {
              const config = ORCH_NODE_CONFIGS[orchType];
              return (
                <div
                  key={orchType}
                  draggable
                  onDragStart={(e) => onDragStart(e, orchType)}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-grab border border-transparent hover:border-[var(--border)] ${config.color} transition-colors`}
                  title={config.description}
                >
                  <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-pink-500/30 text-pink-200">
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

export default OrchPalette;
