'use client';

import { useAgentPoolHealth } from '@/hooks/useSystemHealth';

const STATUS_COLOR: Record<string, string> = {
  active: 'text-[var(--accent)]',
  idle: 'text-[var(--acid-yellow)]',
  failed: 'text-acid-red',
};

const STATUS_DOT: Record<string, string> = {
  active: 'bg-[var(--accent)] shadow-[0_0_4px_var(--acid-green)]',
  idle: 'bg-acid-yellow shadow-[0_0_4px_var(--acid-yellow)]',
  failed: 'bg-acid-red shadow-[0_0_4px_var(--acid-red)]',
};

export function AgentPoolHealth() {
  const { agents, total, active, isLoading, available } = useAgentPoolHealth();

  if (isLoading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-4 bg-surface rounded w-32 mb-4" />
        <div className="h-16 bg-surface rounded" />
      </div>
    );
  }

  const idle = agents.filter((a) => a.status === 'idle').length;
  const failed = agents.filter((a) => a.status === 'failed').length;

  return (
    <div className="card p-6">
      <h3 className="font-theme-data text-[var(--accent)] mb-4">Agent Pool</h3>
      {!available ? (
        <p className="text-text-muted font-theme-data text-xs">Agent registry unavailable</p>
      ) : agents.length === 0 ? (
        <p className="text-text-muted font-theme-data text-xs">No agents registered</p>
      ) : (
        <>
          {/* Summary bar */}
          <div className="flex gap-6 mb-4 font-theme-data text-xs">
            <span className="text-[var(--accent)]">{active} active</span>
            <span className="text-[var(--acid-yellow)]">{idle} idle</span>
            <span className="text-acid-red">{failed} failed</span>
            <span className="text-text-muted">{total} total</span>
          </div>

          {/* Distribution bar */}
          <div className="h-3 bg-surface rounded overflow-hidden border border-border flex mb-4">
            {active > 0 && (
              <div
                className="h-full bg-[var(--accent)] transition-all duration-500"
                style={{ width: `${(active / total) * 100}%` }}
              />
            )}
            {idle > 0 && (
              <div
                className="h-full bg-acid-yellow transition-all duration-500"
                style={{ width: `${(idle / total) * 100}%` }}
              />
            )}
            {failed > 0 && (
              <div
                className="h-full bg-acid-red transition-all duration-500"
                style={{ width: `${(failed / total) * 100}%` }}
              />
            )}
          </div>

          {/* Agent list */}
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {agents.map((a) => (
              <div
                key={a.agent_id}
                className="flex items-center justify-between text-xs font-theme-data py-1 border-b border-border last:border-0"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[a.status] || 'bg-text-muted'}`}
                  />
                  <span className="text-text truncate max-w-[140px]">{a.agent_id}</span>
                  <span className="text-text-muted">{a.type}</span>
                </div>
                <span className={STATUS_COLOR[a.status] || 'text-text-muted'}>
                  {a.status.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
