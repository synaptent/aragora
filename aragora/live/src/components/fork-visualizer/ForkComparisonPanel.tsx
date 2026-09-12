'use client';

import { type ForkComparisonData } from '@/hooks/useDebateFork';

interface ForkComparisonPanelProps {
  comparison: ForkComparisonData;
  onClear: () => void;
}

function ForkCard({ fork, label }: { fork: ForkComparisonData['leftFork']; label: string }) {
  const statusColor =
    {
      created: 'text-[var(--acid-cyan)]',
      running: 'text-[var(--acid-yellow)]',
      completed: 'text-[var(--accent)]',
      unknown: 'text-text-muted',
    }[fork.status || 'unknown'] || 'text-text-muted';

  return (
    <div className="flex-1 p-3 border border-[var(--accent)]/20 bg-surface/30">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] font-theme-data text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 px-1.5 py-0.5 border border-[var(--acid-cyan)]/30">
          {label}
        </span>
        <span className={`text-xs font-theme-data ${statusColor}`}>{fork.status || 'unknown'}</span>
      </div>
      <div className="space-y-1">
        <div className="text-xs font-theme-data text-text">
          {fork.type === 'root' ? 'ROOT DEBATE' : `Fork @ Round ${fork.branch_point}`}
        </div>
        {fork.pivot_claim && (
          <div
            className="text-[10px] font-theme-data text-text-muted line-clamp-2"
            title={fork.pivot_claim}
          >
            {fork.pivot_claim}
          </div>
        )}
        {fork.modified_context && (
          <div className="text-[10px] font-theme-data text-[var(--acid-yellow)]/80 italic">
            Context: {fork.modified_context}
          </div>
        )}
        <div className="text-[10px] font-theme-data text-text-muted">
          Messages: {fork.messages_inherited ?? 'N/A'}
        </div>
      </div>
    </div>
  );
}

export function ForkComparisonPanel({ comparison, onClear }: ForkComparisonPanelProps) {
  const { leftFork, rightFork, divergencePoint, sharedMessages, outcomeDiff } = comparison;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-theme-data text-text-muted">
          COMPARING {leftFork.type === 'root' ? 'ROOT' : `FORK-${leftFork.id.slice(0, 6)}`} vs{' '}
          {rightFork.type === 'root' ? 'ROOT' : `FORK-${rightFork.id.slice(0, 6)}`}
        </div>
        <button
          onClick={onClear}
          className="px-2 py-1 text-[10px] font-theme-data text-text-muted hover:text-acid-red transition-colors"
        >
          [CLEAR]
        </button>
      </div>

      <div className="flex gap-3">
        <ForkCard fork={leftFork} label="L" />
        <ForkCard fork={rightFork} label="R" />
      </div>

      <div className="grid grid-cols-2 gap-3 p-3 border border-[var(--accent)]/20 bg-bg/50">
        <div>
          <div className="text-[10px] font-theme-data text-text-muted mb-1">DIVERGENCE POINT</div>
          <div className="text-sm font-theme-data text-[var(--accent)]">
            Round {divergencePoint}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-theme-data text-text-muted mb-1">SHARED MESSAGES</div>
          <div className="text-sm font-theme-data text-[var(--accent)]">{sharedMessages}</div>
        </div>
      </div>

      {outcomeDiff.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-theme-data text-text-muted">OUTCOME DIFFERENCES</div>
          <div className="space-y-1">
            {outcomeDiff.map((diff, idx) => (
              <div
                key={idx}
                className="grid grid-cols-3 gap-2 p-2 border border-[var(--accent)]/10 text-[10px] font-theme-data"
              >
                <div className="text-text-muted uppercase">{diff.field.replace(/_/g, ' ')}</div>
                <div className="text-[var(--acid-cyan)]">{String(diff.left ?? 'null')}</div>
                <div className="text-[var(--acid-yellow)]">{String(diff.right ?? 'null')}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {outcomeDiff.length === 0 && (
        <div className="text-center py-4 text-xs font-theme-data text-text-muted">
          No significant differences detected in tracked fields.
        </div>
      )}
    </div>
  );
}
