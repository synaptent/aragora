'use client';

import { memo, useCallback } from 'react';
import { NODE_TYPE_CONFIGS, type WorkflowStepType } from './types';

interface NodePaletteProps {
  onDragStart: (type: WorkflowStepType) => void;
}

interface PaletteItemProps {
  type: WorkflowStepType;
  onDragStart: (type: WorkflowStepType) => void;
}

const PaletteItem = memo(function PaletteItem({ type, onDragStart }: PaletteItemProps) {
  const config = NODE_TYPE_CONFIGS[type];

  const handleDragStart = useCallback(
    (event: React.DragEvent) => {
      event.dataTransfer.setData('application/reactflow', type);
      event.dataTransfer.effectAllowed = 'move';
      onDragStart(type);
    },
    [type, onDragStart],
  );

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      className={`
        p-3 rounded-lg border-2 cursor-grab active:cursor-grabbing
        ${config.color} ${config.borderColor}
        hover:scale-105 transition-transform duration-150
        select-none
      `}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">{config.icon}</span>
        <span className="text-sm font-theme-data font-bold text-text">{config.label}</span>
      </div>
      <p className="text-xs text-text-muted">{config.description}</p>
    </div>
  );
});

export function NodePalette({ onDragStart }: NodePaletteProps) {
  return (
    <div className="h-full overflow-y-auto p-4 bg-surface border-r border-border">
      <div className="mb-4">
        <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase tracking-wide mb-1">
          Node Palette
        </h3>
        <p className="text-xs text-text-muted">Drag nodes onto the canvas to build your workflow</p>
      </div>

      <div className="space-y-3">
        {/* Core Nodes */}
        <div className="mb-4">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wide mb-2">
            Core
          </h4>
          <div className="space-y-2">
            <PaletteItem type="debate" onDragStart={onDragStart} />
            <PaletteItem type="task" onDragStart={onDragStart} />
          </div>
        </div>

        {/* Control Flow */}
        <div className="mb-4">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wide mb-2">
            Control Flow
          </h4>
          <div className="space-y-2">
            <PaletteItem type="decision" onDragStart={onDragStart} />
            <PaletteItem type="parallel" onDragStart={onDragStart} />
            <PaletteItem type="loop" onDragStart={onDragStart} />
          </div>
        </div>

        {/* Human Interaction */}
        <div className="mb-4">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wide mb-2">
            Human Review
          </h4>
          <div className="space-y-2">
            <PaletteItem type="human_checkpoint" onDragStart={onDragStart} />
          </div>
        </div>

        {/* Memory Operations */}
        <div className="mb-4">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wide mb-2">
            Memory
          </h4>
          <div className="space-y-2">
            <PaletteItem type="memory_read" onDragStart={onDragStart} />
            <PaletteItem type="memory_write" onDragStart={onDragStart} />
          </div>
        </div>
      </div>

      {/* Help text */}
      <div className="mt-6 p-3 bg-bg border border-border rounded-lg">
        <h4 className="text-xs font-theme-data font-bold text-[var(--accent)] mb-2">Tips</h4>
        <ul className="text-xs text-text-muted space-y-1">
          <li>• Drag nodes from here to the canvas</li>
          <li>• Connect nodes by dragging from handles</li>
          <li>• Click a node to edit its properties</li>
          <li>• Use templates to start quickly</li>
        </ul>
      </div>
    </div>
  );
}

export default NodePalette;
