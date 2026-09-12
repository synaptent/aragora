'use client';

import { memo, useCallback } from 'react';
import {
  PIPELINE_NODE_TYPE_CONFIGS,
  PIPELINE_STAGE_CONFIG,
  type PipelineStageType,
  type NodeTypeConfig,
} from './types';

// =============================================================================
// Props
// =============================================================================

interface PipelinePaletteProps {
  stage: PipelineStageType;
  onDragStart?: () => void;
}

interface PaletteItemProps {
  stage: PipelineStageType;
  subtype: string;
  config: NodeTypeConfig;
  onDragStart?: () => void;
}

// =============================================================================
// PaletteItem (memoised)
// =============================================================================

const PaletteItem = memo(function PaletteItem({
  stage,
  subtype,
  config,
  onDragStart,
}: PaletteItemProps) {
  const handleDragStart = useCallback(
    (event: React.DragEvent) => {
      event.dataTransfer.setData('application/pipeline-node', JSON.stringify({ stage, subtype }));
      event.dataTransfer.effectAllowed = 'move';
      onDragStart?.();
    },
    [stage, subtype, onDragStart],
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

// =============================================================================
// PipelinePalette
// =============================================================================

export function PipelinePalette({ stage, onDragStart }: PipelinePaletteProps) {
  const stageConfig = PIPELINE_STAGE_CONFIG[stage];
  const nodeTypes = PIPELINE_NODE_TYPE_CONFIGS[stage];

  return (
    <div className="h-full overflow-y-auto p-4 bg-surface border-r border-border">
      {/* Header */}
      <div className="mb-4">
        <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase tracking-wide mb-1">
          {stageConfig.label} Nodes
        </h3>
        <p className="text-xs text-text-muted">
          Drag nodes onto the canvas to build your{' '}
          <span style={{ color: stageConfig.primary }}>{stageConfig.label.toLowerCase()}</span>{' '}
          stage
        </p>
      </div>

      {/* Palette items — grouped when entries have group values */}
      <div className="flex flex-col gap-2">
        {(() => {
          const entries = Object.entries(nodeTypes);
          const grouped = new Map<string, typeof entries>();
          for (const entry of entries) {
            const g = entry[1].group || '';
            if (!grouped.has(g)) grouped.set(g, []);
            grouped.get(g)!.push(entry);
          }
          const hasGroups = grouped.size > 1 || (grouped.size === 1 && !grouped.has(''));

          if (!hasGroups) {
            return entries.map(([subtype, config]) => (
              <PaletteItem
                key={subtype}
                stage={stage}
                subtype={subtype}
                config={config}
                onDragStart={onDragStart}
              />
            ));
          }

          return Array.from(grouped.entries()).map(([group, items]) => (
            <div key={group || '_ungrouped'}>
              {group && (
                <h4 className="text-[10px] font-theme-data font-bold text-text-muted uppercase tracking-wider mt-2 mb-1">
                  {group}
                </h4>
              )}
              {items.map(([subtype, config]) => (
                <PaletteItem
                  key={subtype}
                  stage={stage}
                  subtype={subtype}
                  config={config}
                  onDragStart={onDragStart}
                />
              ))}
            </div>
          ));
        })()}
      </div>

      {/* Help tip */}
      <div className="mt-6 p-3 bg-bg border border-border rounded-lg">
        <h4 className="text-xs font-theme-data font-bold text-[var(--accent)] mb-2">Tips</h4>
        <ul className="text-xs text-text-muted space-y-1">
          <li>• Drag nodes from here to the canvas</li>
          <li>• Connect nodes by dragging from handles</li>
          <li>• Click a node to edit its properties</li>
          <li>• Nodes are scoped to the current stage</li>
        </ul>
      </div>
    </div>
  );
}

export default PipelinePalette;
