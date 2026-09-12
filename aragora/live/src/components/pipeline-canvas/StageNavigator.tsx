'use client';

import { memo } from 'react';
import { PIPELINE_STAGE_CONFIG, type PipelineStageType } from './types';

const STAGES: PipelineStageType[] = ['ideas', 'goals', 'actions', 'orchestration'];

interface StageNavigatorProps {
  stageStatus: Record<PipelineStageType, string>;
  activeStage: PipelineStageType;
  onStageSelect: (stage: PipelineStageType) => void;
  onAdvance?: (stage: PipelineStageType) => void;
  readOnly?: boolean;
}

export const StageNavigator = memo(function StageNavigator({
  stageStatus,
  activeStage,
  onStageSelect,
  onAdvance,
  readOnly,
}: StageNavigatorProps) {
  const nextPendingStage = STAGES.find((s) => stageStatus[s] !== 'complete');

  return (
    <div className="flex items-center gap-1 bg-surface/90 border border-border rounded-lg p-2">
      {STAGES.map((stage, i) => {
        const config = PIPELINE_STAGE_CONFIG[stage];
        const status = stageStatus[stage] || 'pending';
        const isActive = stage === activeStage;
        const isComplete = status === 'complete';
        const isPending = status === 'pending';

        return (
          <div key={stage} className="flex items-center">
            <button
              onClick={() => onStageSelect(stage)}
              className={`
                px-3 py-1.5 rounded font-theme-data text-xs font-bold uppercase tracking-wide
                transition-all duration-200 flex items-center gap-1.5
                ${isActive ? 'ring-2 ring-acid-green ring-offset-1 ring-offset-bg' : ''}
                ${isComplete ? 'opacity-100' : 'opacity-50'}
              `}
              style={{
                backgroundColor: `${config.primary}33`,
                color: config.primary,
                borderColor: config.primary,
              }}
            >
              {isComplete && <span>&#10003;</span>}
              {isActive && !isComplete && <span>&rarr;</span>}
              {isPending && !isActive && <span>&#9675;</span>}
              {config.label}
            </button>

            {i < STAGES.length - 1 && (
              <div className={`w-6 h-0.5 mx-1 ${isComplete ? 'bg-text-muted' : 'bg-border'}`} />
            )}
          </div>
        );
      })}

      {!readOnly && nextPendingStage && onAdvance && (
        <button
          onClick={() => onAdvance(nextPendingStage)}
          className="ml-2 px-3 py-1.5 bg-[var(--accent)] text-bg font-theme-data text-xs font-bold rounded hover:bg-[var(--accent)]/80 transition-colors"
        >
          ADVANCE
        </button>
      )}
    </div>
  );
});

export default StageNavigator;
