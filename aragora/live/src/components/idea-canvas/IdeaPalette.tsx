'use client';

import { IDEA_NODE_CONFIGS, type IdeaNodeType } from './types';

const groups: { label: string; types: IdeaNodeType[] }[] = [
  { label: 'Core', types: ['concept', 'observation', 'question'] },
  { label: 'Analysis', types: ['hypothesis', 'insight', 'evidence'] },
  { label: 'Structure', types: ['cluster', 'assumption', 'constraint'] },
];

/**
 * Drag-and-drop palette for adding idea nodes to the canvas.
 */
export function IdeaPalette() {
  const onDragStart = (e: React.DragEvent, ideaType: IdeaNodeType) => {
    e.dataTransfer.setData('application/idea-node-type', ideaType);
    e.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div className="w-56 flex-shrink-0 border-r border-[var(--border)] bg-[var(--bg)] overflow-y-auto p-3">
      <h3 className="text-xs font-bold text-[var(--text-muted)] mb-3 uppercase tracking-wider">
        Idea Nodes
      </h3>
      {groups.map((group) => (
        <div key={group.label} className="mb-4">
          <h4 className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-2">
            {group.label}
          </h4>
          <div className="space-y-1">
            {group.types.map((type) => {
              const config = IDEA_NODE_CONFIGS[type];
              return (
                <div
                  key={type}
                  draggable
                  onDragStart={(e) => onDragStart(e, type)}
                  className={`
                    cursor-grab active:cursor-grabbing
                    px-3 py-2 rounded border ${config.borderColor} ${config.color}
                    hover:scale-[1.02] transition-transform
                    font-theme-data text-xs
                  `}
                >
                  <div className="flex items-center gap-2">
                    <span className="opacity-60">{config.icon}</span>
                    <span className="text-[var(--text)]">{config.label}</span>
                  </div>
                  <p className="text-[9px] text-[var(--text-muted)] mt-0.5">{config.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export default IdeaPalette;
