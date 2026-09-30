'use client';

import { useRetentionDecisions } from '@/hooks/useUnifiedMemory';

const ACTION_COLORS: Record<string, string> = {
  retain: 'text-emerald-400 border-emerald-400/30',
  demote: 'text-amber-400 border-amber-400/30',
  forget: 'text-red-400 border-red-400/30',
  consolidate: 'text-blue-400 border-blue-400/30',
};

export function RetentionDecisions() {
  const { decisions, stats, loading } = useRetentionDecisions();

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading retention decisions...
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="flex gap-4 font-theme-data text-xs">
        <span className="text-emerald-400">Retained: {stats.retained}</span>
        <span className="text-amber-400">Demoted: {stats.demoted}</span>
        <span className="text-red-400">Forgotten: {stats.forgotten}</span>
        <span className="text-blue-400">Consolidated: {stats.consolidated}</span>
      </div>

      {decisions.length === 0 ? (
        <p className="text-[var(--text-muted)] font-theme-data text-sm p-4">
          No retention decisions yet. Enable the RetentionGate to see surprise-driven memory
          management.
        </p>
      ) : (
        <div className="space-y-2">
          {decisions.map((d, i) => (
            <div
              key={d.memory_id || i}
              className={`card p-3 border-l-2 ${ACTION_COLORS[d.action] || ''}`}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className={`text-[10px] font-theme-data uppercase px-2 py-0.5 border rounded ${ACTION_COLORS[d.action] || ''}`}
                >
                  {d.action}
                </span>
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {d.timestamp}
                </span>
              </div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  Surprise:
                </span>
                <div className="flex-1 h-1.5 bg-[var(--bg)] rounded overflow-hidden max-w-[100px]">
                  <div
                    className="h-full bg-[var(--acid-green)]"
                    style={{ width: `${d.surprise_score * 100}%` }}
                  />
                </div>
                <span className="text-[10px] font-theme-data text-[var(--acid-green)]">
                  {(d.surprise_score * 100).toFixed(0)}%
                </span>
              </div>
              {d.reason && (
                <p className="text-xs font-theme-data text-[var(--text-muted)]">{d.reason}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
