'use client';

import React from 'react';
import { VERDICT_CONFIG } from './types';

interface VerdictBadgeProps {
  verdict: string;
}

export function VerdictBadge({ verdict }: VerdictBadgeProps) {
  const config = VERDICT_CONFIG[verdict] || VERDICT_CONFIG.UNKNOWN;
  return (
    <span
      className={`px-2 py-1 rounded text-xs font-theme-data ${config.bg} ${config.border} ${config.text} border`}
    >
      {config.icon} {verdict}
    </span>
  );
}
