'use client';

import { useSystemHealth } from '@/hooks/useSystemHealth';

const STATUS_CONFIG: Record<string, { color: string; bg: string; glow: string; label: string }> = {
  healthy: {
    color: 'text-[var(--accent)]',
    bg: 'bg-[var(--accent)]',
    glow: 'shadow-[0_0_12px_var(--acid-green)]',
    label: 'ALL SYSTEMS OPERATIONAL',
  },
  degraded: {
    color: 'text-[var(--acid-yellow)]',
    bg: 'bg-acid-yellow',
    glow: 'shadow-[0_0_12px_var(--acid-yellow)]',
    label: 'DEGRADED PERFORMANCE',
  },
  critical: {
    color: 'text-acid-red',
    bg: 'bg-acid-red',
    glow: 'shadow-[0_0_12px_var(--acid-red)]',
    label: 'CRITICAL ISSUES DETECTED',
  },
};

const SUBSYSTEM_STATUS_COLOR: Record<string, string> = {
  healthy: 'border-[var(--accent)] text-[var(--accent)]',
  degraded: 'border-acid-yellow text-[var(--acid-yellow)]',
  critical: 'border-acid-red text-acid-red',
  unknown: 'border-text-muted text-text-muted',
};

export function SystemHealthSummary() {
  const { health, isLoading } = useSystemHealth();

  if (isLoading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-5 bg-surface rounded w-48 mb-2" />
        <div className="h-3 bg-surface rounded w-32" />
      </div>
    );
  }

  if (!health) {
    return (
      <div className="card p-6">
        <p className="font-theme-data text-sm text-text-muted">
          Unable to load system health data.
        </p>
      </div>
    );
  }

  const config = STATUS_CONFIG[health.overall_status] || STATUS_CONFIG.healthy;
  const subsystems = Object.entries(health.subsystems);
  const healthy = subsystems.filter(([, s]) => s === 'healthy').length;
  const degraded = subsystems.filter(([, s]) => s === 'degraded').length;
  const critical = subsystems.filter(([, s]) => s === 'critical').length;

  return (
    <div className="space-y-4">
      {/* Main status banner */}
      <div className="card p-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className={`w-4 h-4 rounded-full ${config.bg} ${config.glow} animate-pulse`} />
          <div>
            <h2 className={`font-theme-data text-lg font-bold ${config.color}`}>{config.label}</h2>
            <p className="font-theme-data text-xs text-text-muted">
              Last check:{' '}
              {health.last_check ? new Date(health.last_check).toLocaleTimeString() : 'N/A'}
            </p>
          </div>
        </div>
        <span className="font-theme-data text-xs text-text-muted">
          Collected in {health.collection_time_ms}ms
        </span>
      </div>

      {/* Summary counts */}
      <div className="flex gap-6 font-theme-data text-xs">
        <span className="text-[var(--accent)]">{healthy} healthy</span>
        {degraded > 0 && <span className="text-[var(--acid-yellow)]">{degraded} degraded</span>}
        {critical > 0 && <span className="text-acid-red">{critical} critical</span>}
      </div>

      {/* Subsystem status cards */}
      {subsystems.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
          {subsystems.map(([name, status]) => {
            const statusColor = SUBSYSTEM_STATUS_COLOR[status] || SUBSYSTEM_STATUS_COLOR.unknown;
            return (
              <div key={name} className={`card p-3 border-l-2 ${statusColor.split(' ')[0]}`}>
                <span className="font-theme-data text-xs text-text capitalize">
                  {name.replace(/_/g, ' ')}
                </span>
                <span
                  className={`block text-[10px] font-theme-data uppercase ${statusColor.split(' ')[1]}`}
                >
                  {status}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
