'use client';

export interface StatItem {
  value: string | number;
  label: string;
  color?: string;
}

export interface StatsGridProps {
  stats: StatItem[];
  columns?: 2 | 3 | 4;
  className?: string;
}

export function StatsGrid({ stats, columns = 3, className = '' }: StatsGridProps) {
  const gridCols = { 2: 'grid-cols-2', 3: 'grid-cols-3', 4: 'grid-cols-4' };

  return (
    <div className={`grid ${gridCols[columns]} gap-3 ${className}`}>
      {stats.map((stat, index) => (
        <div key={index} className="p-3 bg-bg border border-border rounded-lg text-center">
          <div className={`text-2xl font-theme-data ${stat.color || 'text-accent'}`}>
            {stat.value}
          </div>
          <div className="text-xs text-text-muted">{stat.label}</div>
        </div>
      ))}
    </div>
  );
}
