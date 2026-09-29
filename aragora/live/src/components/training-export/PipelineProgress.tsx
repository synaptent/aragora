'use client';

import { memo } from 'react';
import type { PipelineStatus } from './types';
import { STAGE_LABELS, STAGE_COLORS } from './types';

interface PipelineProgressProps {
  status: PipelineStatus;
}

function PipelineProgressComponent({ status }: PipelineProgressProps) {
  return (
    <div className="bg-slate-800 rounded-lg p-4 mb-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-white">
          {status.message || STAGE_LABELS[status.stage]}
        </span>
        <span className="text-xs text-slate-400">
          {status.recordsProcessed > 0 && (
            <>
              {status.recordsProcessed.toLocaleString()} / {status.totalRecords.toLocaleString()}{' '}
              records
            </>
          )}
        </span>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all duration-300 ${STAGE_COLORS[status.stage]}`}
          style={{ width: `${Math.min(status.progress, 100)}%` }}
        />
      </div>
      <div className="flex justify-between mt-2 text-xs text-slate-500">
        <span className={status.stage !== 'idle' ? 'text-blue-400' : ''}>Collect</span>
        <span
          className={
            ['filtering', 'transforming', 'exporting', 'complete'].includes(status.stage)
              ? 'text-cyan-400'
              : ''
          }
        >
          Filter
        </span>
        <span
          className={
            ['transforming', 'exporting', 'complete'].includes(status.stage)
              ? 'text-purple-400'
              : ''
          }
        >
          Transform
        </span>
        <span className={['exporting', 'complete'].includes(status.stage) ? 'text-green-400' : ''}>
          Export
        </span>
      </div>
    </div>
  );
}

export const PipelineProgress = memo(PipelineProgressComponent);
