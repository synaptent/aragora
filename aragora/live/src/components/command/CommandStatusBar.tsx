'use client';

import type { CommandStats } from '@/hooks/useCommandCenter';

interface CommandStatusBarProps {
  stats: CommandStats;
  onAutoFlowAll: () => void;
  onValidateAll: () => void;
  onExecuteReady: () => void;
  loading: boolean;
}

export function CommandStatusBar({
  stats,
  onAutoFlowAll,
  onValidateAll,
  onExecuteReady,
  loading,
}: CommandStatusBarProps) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface">
      {/* Left: Title */}
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-theme-data font-bold text-[var(--accent)] uppercase tracking-wider">
          Command Center
        </h2>
        {loading && (
          <div className="w-3 h-3 border-2 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin" />
        )}
      </div>

      {/* Center: Stats */}
      <div className="hidden md:flex items-center gap-3">
        <StatChip label="Active" value={stats.activeOps} color="blue" />
        <StatChip label="Budget" value={`$${stats.budgetConsumed.toFixed(2)}`} color="amber" />
        <StatChip label="Agents" value={stats.agentsActive} color="emerald" />
        <StatChip label="Nodes" value={stats.totalNodes} color="indigo" />
      </div>

      {/* Right: Quick Actions */}
      <div className="flex items-center gap-2">
        <ActionButton label="Auto-Flow All" onClick={onAutoFlowAll} disabled={loading} />
        <ActionButton label="Validate All" onClick={onValidateAll} disabled={loading} />
        <ActionButton label="Execute Ready" onClick={onExecuteReady} disabled={loading} accent />
      </div>
    </div>
  );
}

function StatChip({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  const colorMap: Record<string, string> = {
    blue: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    amber: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    indigo: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
  };
  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-theme-data border ${colorMap[color] || colorMap.blue}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-bold">{value}</span>
    </div>
  );
}

function ActionButton({
  label,
  onClick,
  disabled,
  accent,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  accent?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 text-xs font-theme-data rounded transition-colors disabled:opacity-50 ${
        accent
          ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/30'
          : 'text-text-muted hover:text-text hover:bg-bg border border-border'
      }`}
    >
      {label}
    </button>
  );
}
