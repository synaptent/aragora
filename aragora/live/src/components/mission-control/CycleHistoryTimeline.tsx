'use client';

import { memo } from 'react';

export interface CycleHistoryEntry {
  cycleId: string;
  objective: string;
  success: boolean;
  lesson?: string;
  completedAt: number;
  metrics?: { testsAdded?: number; filesTouched?: number; duration?: number };
}

export interface CycleHistoryTimelineProps {
  entries: CycleHistoryEntry[];
  maxEntries?: number;
}

export const CycleHistoryTimeline = memo(function CycleHistoryTimeline({
  entries,
  maxEntries = 10,
}: CycleHistoryTimelineProps) {
  const visible = entries.slice(0, maxEntries);
  const successCount = visible.filter((e) => e.success).length;
  const failCount = visible.filter((e) => !e.success).length;

  if (visible.length === 0) {
    return (
      <div className="text-xs font-theme-data text-[var(--text-muted)] p-3">
        No cycle history yet
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="cycle-history-timeline">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-sm">📜</span>
          <span className="text-xs font-theme-data font-bold text-[var(--text)]">
            Cycle History
          </span>
        </div>
        <div className="flex gap-2 text-xs font-theme-data">
          <span className="text-emerald-400">{successCount} learned</span>
          {failCount > 0 && <span className="text-red-400">{failCount} failed</span>}
        </div>
      </div>

      <div className="space-y-1">
        {visible.map((entry) => (
          <div
            key={entry.cycleId}
            className={`p-2 rounded border ${
              entry.success
                ? 'border-emerald-500/30 bg-emerald-500/5'
                : 'border-red-500/30 bg-red-500/5'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className={`text-xs ${entry.success ? 'text-emerald-400' : 'text-red-400'}`}>
                {entry.success ? '✓' : '✗'}
              </span>
              <span className="text-xs font-theme-data text-[var(--text)] truncate flex-1">
                {entry.objective}
              </span>
              <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                {entry.cycleId.slice(0, 8)}
              </span>
            </div>
            {entry.lesson && (
              <p className="text-xs text-[var(--text-muted)] mt-1 ml-5">{entry.lesson}</p>
            )}
            {entry.metrics && (
              <div className="flex gap-2 mt-1 ml-5 text-[10px] font-theme-data text-[var(--text-muted)]">
                {entry.metrics.testsAdded != null && <span>+{entry.metrics.testsAdded} tests</span>}
                {entry.metrics.filesTouched != null && (
                  <span>{entry.metrics.filesTouched} files</span>
                )}
                {entry.metrics.duration != null && (
                  <span>{Math.round(entry.metrics.duration / 1000)}s</span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
});

export default CycleHistoryTimeline;
