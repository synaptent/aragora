/**
 * FractalMiniMap — collapsed 4-stage overview with current position highlighting.
 *
 * Shows a compact horizontal strip of the 4 pipeline stages with color-coded
 * status and an indicator for the active stage / drill depth.
 */

import { memo } from 'react';
import type { PipelineStageType } from './types';

const STAGES: PipelineStageType[] = ['ideas', 'principles', 'goals', 'actions', 'orchestration'];

const STAGE_COLORS: Record<PipelineStageType, string> = {
  ideas: '#3B82F6',
  principles: '#8B5CF6',
  goals: '#10B981',
  actions: '#F59E0B',
  orchestration: '#8B5CF6',
};

const STATUS_OPACITY: Record<string, number> = { complete: 1.0, in_progress: 0.7, pending: 0.3 };

interface FractalMiniMapProps {
  stageStatus: Record<PipelineStageType, string>;
  activeStage: PipelineStageType;
  drillDepth: number;
  onStageSelect: (stage: PipelineStageType) => void;
}

export const FractalMiniMap = memo(function FractalMiniMap({
  stageStatus,
  activeStage,
  drillDepth,
  onStageSelect,
}: FractalMiniMapProps) {
  return (
    <div className="flex items-center gap-1 bg-bg-secondary/80 backdrop-blur-sm rounded-lg px-2 py-1.5 shadow-md border border-border-primary/30">
      {STAGES.map((stage) => {
        const isActive = stage === activeStage;
        const status = stageStatus[stage] ?? 'pending';
        const opacity = STATUS_OPACITY[status] ?? 0.3;
        const color = STAGE_COLORS[stage];

        return (
          <button
            key={stage}
            onClick={() => onStageSelect(stage)}
            className="relative flex items-center justify-center transition-all duration-200"
            style={{ opacity }}
            title={`${stage} (${status})`}
            aria-label={`Navigate to ${stage} stage (${status})`}
          >
            <div
              className="rounded-sm transition-all duration-200"
              style={{
                width: isActive ? 24 : 16,
                height: isActive ? 12 : 8,
                backgroundColor: color,
                boxShadow: isActive ? `0 0 6px ${color}60` : 'none',
              }}
            />
            {isActive && drillDepth > 0 && (
              <span className="absolute -top-1 -right-1 text-[8px] font-bold text-text-primary bg-bg-primary rounded-full w-3 h-3 flex items-center justify-center border border-border-primary">
                {drillDepth}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
});
