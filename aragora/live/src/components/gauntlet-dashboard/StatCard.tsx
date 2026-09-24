'use client';

import React from 'react';

interface StatCardProps {
  label: string;
  value: number | string;
  subValue?: string;
  color?: string;
  icon?: string;
}

export function StatCard({ label, value, subValue, color = 'acid-green', icon }: StatCardProps) {
  return (
    <div className="p-4 bg-surface/50 border border-border rounded-lg">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-theme-data text-text-muted">{label}</span>
        {icon && <span className="text-lg">{icon}</span>}
      </div>
      <div className={`text-2xl font-theme-data text-${color}`}>{value}</div>
      {subValue && <div className="text-xs font-theme-data text-text-muted mt-1">{subValue}</div>}
    </div>
  );
}
