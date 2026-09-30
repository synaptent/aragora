'use client';

interface ProgressBarProps {
  current: number;
  total: number;
}

export function ProgressBar({ current, total }: ProgressBarProps) {
  const percentage = Math.round((current / total) * 100);

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-theme-data text-text-muted">
          Step {current} of {total}
        </span>
        <span className="text-xs font-theme-data text-[var(--accent)]">{percentage}%</span>
      </div>
      <div className="w-full h-1 bg-[var(--accent)]/20 rounded-full overflow-hidden">
        <div
          className="h-full bg-[var(--accent)] transition-all duration-300 ease-out"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
