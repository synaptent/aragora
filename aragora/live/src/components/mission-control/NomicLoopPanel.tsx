'use client';

import { memo } from 'react';

export type NomicPhase =
  'idle' | 'planning' | 'decomposing' | 'executing' | 'verifying' | 'complete';

export interface NomicLoopPanelProps {
  phase: NomicPhase;
  currentGoal?: string;
  cycleId?: string;
  progress?: number;
}

const PHASES: { key: NomicPhase; label: string; icon: string }[] = [
  { key: 'planning', label: 'Plan', icon: '📋' },
  { key: 'decomposing', label: 'Decompose', icon: '🧩' },
  { key: 'executing', label: 'Execute', icon: '⚡' },
  { key: 'verifying', label: 'Verify', icon: '✓' },
];

export const NomicLoopPanel = memo(function NomicLoopPanel({
  phase,
  currentGoal,
  cycleId,
  progress,
}: NomicLoopPanelProps) {
  const activeIdx = PHASES.findIndex((p) => p.key === phase);

  return (
    <div
      className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg"
      data-testid="nomic-loop-panel"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-sm">🔄</span>
          <span className="text-xs font-theme-data font-bold text-[var(--text)]">Nomic Loop</span>
        </div>
        {cycleId && (
          <span className="text-xs font-theme-data text-[var(--text-muted)]">
            cycle: {cycleId.slice(0, 8)}
          </span>
        )}
      </div>

      {/* Phase progress dots */}
      <div className="flex items-center gap-1 mb-2">
        {PHASES.map((p, i) => {
          const isActive = i === activeIdx;
          const isComplete = i < activeIdx;
          const isPending = i > activeIdx || phase === 'idle';

          return (
            <div key={p.key} className="flex items-center gap-1">
              <div
                className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-theme-data
                  ${isActive ? 'bg-blue-500/20 text-blue-400 animate-pulse' : ''}
                  ${isComplete ? 'bg-emerald-500/20 text-emerald-400' : ''}
                  ${isPending ? 'text-[var(--text-muted)]' : ''}
                `}
                title={p.label}
              >
                <span>{p.icon}</span>
                <span>{p.label}</span>
              </div>
              {i < PHASES.length - 1 && (
                <span
                  className={`text-xs ${isComplete ? 'text-emerald-400' : 'text-[var(--text-muted)]'}`}
                >
                  →
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Current goal */}
      {currentGoal && (
        <div className="text-xs text-[var(--text)] bg-[var(--bg)] rounded p-2 border border-[var(--border)]">
          {currentGoal}
        </div>
      )}

      {/* Progress bar */}
      {progress != null && phase !== 'idle' && phase !== 'complete' && (
        <div className="mt-2">
          <div className="h-1 bg-[var(--border)] rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--acid-green)] rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, progress)}%` }}
            />
          </div>
        </div>
      )}

      {phase === 'complete' && (
        <div className="mt-2 text-xs font-theme-data text-emerald-400 flex items-center gap-1">
          <span>✓</span> Cycle complete
        </div>
      )}
    </div>
  );
});

export default NomicLoopPanel;
