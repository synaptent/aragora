'use client';

import { memo, useMemo } from 'react';
import { type PipelineStageType } from './types';

const STAGES: PipelineStageType[] = ['ideas', 'goals', 'actions', 'orchestration'];

interface ProgressIndicatorProps {
  stageStatus: Record<PipelineStageType, string>;
  activeStage: PipelineStageType;
}

export const ProgressIndicator = memo(function ProgressIndicator({
  stageStatus,
  activeStage,
}: ProgressIndicatorProps) {
  const completedCount = useMemo(
    () => STAGES.filter((s) => stageStatus[s] === 'complete').length,
    [stageStatus],
  );

  const progressPct = (completedCount / STAGES.length) * 100;

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 bg-surface/80 border border-border rounded-lg">
      {/* Progress bar */}
      <div className="w-24 h-1.5 bg-bg rounded-full overflow-hidden">
        <div
          className="h-full bg-[var(--accent)] rounded-full transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Stage labels */}
      <div className="flex items-center gap-1">
        {STAGES.map((stage, i) => {
          const isComplete = stageStatus[stage] === 'complete';
          const isCurrent = stage === activeStage;

          return (
            <div key={stage} className="flex items-center">
              <span
                className={`text-[10px] font-theme-data font-bold uppercase tracking-wider ${
                  isComplete
                    ? 'text-[var(--accent)]'
                    : isCurrent
                      ? 'text-text'
                      : 'text-text-muted/50'
                }`}
              >
                {isComplete ? '\u2713' : i + 1}
              </span>
              {i < STAGES.length - 1 && (
                <span className="text-text-muted/30 mx-0.5 text-[8px]">&middot;</span>
              )}
            </div>
          );
        })}
      </div>

      {/* Count label */}
      <span className="text-[10px] font-theme-data text-text-muted">
        {completedCount}/{STAGES.length}
      </span>
    </div>
  );
});

export default ProgressIndicator;
