'use client';

interface AutoFlowOrchestratorProps {
  currentPhase: string;
  phaseProgress: number;
  nodesCreated: number;
  onPause: () => void;
  onSkipToEnd: () => void;
  onCancel: () => void;
}

const PHASES = [
  { key: 'clustering', label: 'Clustering Ideas', icon: '\u{1F4A1}', color: 'indigo' },
  { key: 'goals', label: 'Extracting Goals', icon: '\u{1F3AF}', color: 'emerald' },
  { key: 'tasks', label: 'Decomposing into Tasks', icon: '\u2702', color: 'amber' },
  { key: 'agents', label: 'Assigning Agents', icon: '\u{1F916}', color: 'pink' },
  { key: 'validating', label: 'Validating', icon: '\u{1F52C}', color: 'violet' },
];

const PHASE_COLOR_MAP: Record<string, { active: string; bg: string; border: string }> = {
  indigo: { active: 'text-indigo-400', bg: 'bg-indigo-500/20', border: 'border-indigo-500/40' },
  emerald: { active: 'text-emerald-400', bg: 'bg-emerald-500/20', border: 'border-emerald-500/40' },
  amber: { active: 'text-amber-400', bg: 'bg-amber-500/20', border: 'border-amber-500/40' },
  pink: { active: 'text-pink-400', bg: 'bg-pink-500/20', border: 'border-pink-500/40' },
  violet: { active: 'text-violet-400', bg: 'bg-violet-500/20', border: 'border-violet-500/40' },
};

export function AutoFlowOrchestrator({
  currentPhase,
  phaseProgress,
  nodesCreated,
  onPause,
  onSkipToEnd,
  onCancel,
}: AutoFlowOrchestratorProps) {
  const currentIndex = PHASES.findIndex((p) => p.key === currentPhase);
  const overallPct = Math.round(((currentIndex + phaseProgress) / PHASES.length) * 100);

  return (
    <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm z-20 flex items-center justify-center">
      <div className="bg-surface border border-border rounded-xl p-6 w-[480px] shadow-2xl">
        {/* Progress Bar with percentage */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex-1 h-2 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] rounded-full transition-all duration-500"
              style={{ width: `${overallPct}%` }}
            />
          </div>
          <span className="text-xs font-theme-data text-[var(--accent)] font-bold w-10 text-right">
            {overallPct}%
          </span>
        </div>

        {/* Phase List */}
        <div className="space-y-3 mb-6">
          {PHASES.map((phase, i) => {
            const isActive = i === currentIndex;
            const isDone = i < currentIndex;
            const colors = PHASE_COLOR_MAP[phase.color] || PHASE_COLOR_MAP.indigo;
            const phasePct = isDone ? 100 : isActive ? Math.round(phaseProgress * 100) : 0;

            return (
              <div
                key={phase.key}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${
                  isActive
                    ? `${colors.bg} border ${colors.border}`
                    : isDone
                      ? 'opacity-70'
                      : 'opacity-30'
                }`}
              >
                {/* Status indicator */}
                <div className="w-6 h-6 flex items-center justify-center flex-shrink-0">
                  {isDone ? (
                    <span className="text-emerald-400 text-sm">{'\u2713'}</span>
                  ) : isActive ? (
                    <div className="w-4 h-4 border-2 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin" />
                  ) : (
                    <span className="text-text-muted text-xs">{i + 1}</span>
                  )}
                </div>

                {/* Phase info */}
                <span className="text-lg">{phase.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-sm font-theme-data ${isActive ? 'text-text font-bold' : 'text-text-muted'}`}
                    >
                      {phase.label}
                    </span>
                    {isActive && (
                      <span className={`text-xs font-theme-data ${colors.active}`}>
                        ({nodesCreated} nodes)
                      </span>
                    )}
                  </div>
                  {/* Per-phase progress bar */}
                  {(isActive || isDone) && (
                    <div className="h-1 bg-bg/50 rounded-full mt-1 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${
                          isDone ? 'bg-emerald-500' : 'bg-[var(--accent)]'
                        }`}
                        style={{ width: `${phasePct}%` }}
                      />
                    </div>
                  )}
                </div>

                {/* Phase percentage */}
                <span
                  className={`text-xs font-theme-data min-w-[3ch] text-right ${
                    isDone ? 'text-emerald-400' : isActive ? colors.active : 'text-text-muted'
                  }`}
                >
                  {phasePct}%
                </span>
              </div>
            );
          })}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-between">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs font-theme-data text-red-400 hover:bg-red-500/10 rounded transition-colors"
          >
            Cancel
          </button>
          <div className="flex gap-2">
            <button
              onClick={onPause}
              className="px-3 py-1.5 text-xs font-theme-data text-text-muted border border-border rounded hover:bg-bg transition-colors"
            >
              Pause
            </button>
            <button
              onClick={onSkipToEnd}
              className="px-3 py-1.5 text-xs font-theme-data text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/10 transition-colors"
            >
              Skip to End
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
