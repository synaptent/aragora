'use client';

import { ReactNode } from 'react';

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  change?: { value: number; direction: 'up' | 'down' | 'neutral'; period: string };
  icon?: ReactNode;
  color?: 'green' | 'cyan' | 'yellow' | 'red' | 'purple';
  loading?: boolean;
}

const colorMap = {
  green: {
    border: 'border-green-500/30',
    bg: 'bg-green-500/10',
    text: 'text-green-400',
    glow: 'shadow-green-500/20',
  },
  cyan: {
    border: 'border-cyan-500/30',
    bg: 'bg-cyan-500/10',
    text: 'text-cyan-400',
    glow: 'shadow-cyan-500/20',
  },
  yellow: {
    border: 'border-yellow-500/30',
    bg: 'bg-yellow-500/10',
    text: 'text-yellow-400',
    glow: 'shadow-yellow-500/20',
  },
  red: {
    border: 'border-red-500/30',
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    glow: 'shadow-red-500/20',
  },
  purple: {
    border: 'border-purple-500/30',
    bg: 'bg-purple-500/10',
    text: 'text-purple-400',
    glow: 'shadow-purple-500/20',
  },
};

export function KPICard({
  title,
  value,
  subtitle,
  change,
  icon,
  color = 'green',
  loading = false,
}: KPICardProps) {
  const colors = colorMap[color];

  return (
    <div
      className={`bg-[var(--surface)] border ${colors.border} p-4 hover:shadow-lg ${colors.glow} transition-all duration-200`}
    >
      <div className="flex items-start justify-between mb-3">
        <span className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
          {title}
        </span>
        {icon && <span className={`text-lg ${colors.text}`}>{icon}</span>}
      </div>

      {loading ? (
        <div className="animate-pulse">
          <div className="h-8 bg-[var(--border)] rounded w-24 mb-2" />
          <div className="h-4 bg-[var(--border)] rounded w-16" />
        </div>
      ) : (
        <>
          <div className={`text-2xl font-theme-data font-bold ${colors.text} mb-1`}>{value}</div>

          {subtitle && (
            <div className="text-xs font-theme-data text-[var(--text-muted)]">{subtitle}</div>
          )}

          {change && (
            <div className="flex items-center gap-1 mt-2 text-xs font-theme-data">
              <span
                className={
                  change.direction === 'up'
                    ? 'text-green-400'
                    : change.direction === 'down'
                      ? 'text-red-400'
                      : 'text-[var(--text-muted)]'
                }
              >
                {change.direction === 'up' && ''}
                {change.direction === 'down' && ''}
                {change.direction === 'neutral' && ''} {Math.abs(change.value)}%
              </span>
              <span className="text-[var(--text-muted)]">vs {change.period}</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface KPIGridProps {
  children: ReactNode;
  columns?: 2 | 3 | 4 | 5;
}

export function KPIGrid({ children, columns = 4 }: KPIGridProps) {
  const gridCols = {
    2: 'grid-cols-1 md:grid-cols-2',
    3: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3',
    4: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-4',
    5: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-5',
  };

  return <div className={`grid ${gridCols[columns]} gap-4`}>{children}</div>;
}

export function KPIMiniCard({
  label,
  value,
  color = 'green',
}: {
  label: string;
  value: string | number;
  color?: 'green' | 'cyan' | 'yellow' | 'red' | 'purple';
}) {
  const colors = colorMap[color];

  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0">
      <span className="text-xs font-theme-data text-[var(--text-muted)]">{label}</span>
      <span className={`text-sm font-theme-data font-bold ${colors.text}`}>{value}</span>
    </div>
  );
}

export default KPICard;
