'use client';

interface CycleEntry {
  cycle: number;
  phase: string;
  files_modified?: number;
  tests_added?: number;
  duration_seconds?: number;
  success: boolean;
  timestamp: string;
}

interface CycleTimelineProps {
  cycles: CycleEntry[];
}

export function CycleTimeline({ cycles }: CycleTimelineProps) {
  if (cycles.length === 0) {
    return (
      <div className="text-center text-text-muted font-theme-data text-xs py-4">
        No cycle history available
      </div>
    );
  }

  return (
    <div className="relative pl-6">
      {/* Vertical connector line */}
      <div className="absolute left-[9px] top-2 bottom-2 w-px bg-border" />

      <div className="space-y-4">
        {cycles.map((entry, idx) => (
          <div key={`${entry.cycle}-${idx}`} className="relative">
            {/* Dot indicator */}
            <div
              className={`absolute -left-6 top-1 w-[10px] h-[10px] rounded-full border-2 ${
                entry.success
                  ? 'bg-[var(--accent)] border-[var(--accent)]'
                  : 'bg-[var(--crimson)] border-[var(--crimson)]'
              }`}
            />

            <div className="bg-surface rounded border border-border p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="font-theme-data text-sm text-text">Cycle {entry.cycle}</span>
                <span
                  className={`font-theme-data text-xs px-1.5 py-0.5 rounded ${
                    entry.success
                      ? 'text-[var(--accent)] bg-[var(--accent)]/10'
                      : 'text-[var(--crimson)] bg-[var(--crimson)]/10'
                  }`}
                >
                  {entry.success ? 'PASS' : 'FAIL'}
                </span>
              </div>

              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs font-theme-data text-text-muted">
                <span>phase: {entry.phase}</span>
                {entry.files_modified != null && <span>{entry.files_modified} files</span>}
                {entry.tests_added != null && <span>+{entry.tests_added} tests</span>}
                {entry.duration_seconds != null && <span>{entry.duration_seconds}s</span>}
              </div>

              <div className="text-xs font-theme-data text-text-muted/60 mt-1">
                {new Date(entry.timestamp).toLocaleString()}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
