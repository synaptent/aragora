'use client';

export interface MetricCardProps {
  label: string;
  value: string | number;
  color?: string;
}

export function MetricCard({ label, value, color = 'text-[var(--accent)]' }: MetricCardProps) {
  return (
    <div className="bg-bg/50 border border-[var(--accent)]/20 p-3 text-center">
      <div className="text-xs font-theme-data text-text-muted mb-1">{label}</div>
      <div className={`text-lg font-theme-data ${color}`}>{value}</div>
    </div>
  );
}

export default MetricCard;
