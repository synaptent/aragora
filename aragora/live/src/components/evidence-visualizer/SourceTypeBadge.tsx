'use client';

/**
 * Source type badge component for displaying evidence source types
 */

import React from 'react';
import { SOURCE_TYPE_CONFIG } from './types';

interface SourceTypeBadgeProps {
  sourceType?: string;
}

export function SourceTypeBadge({ sourceType }: SourceTypeBadgeProps) {
  const config = SOURCE_TYPE_CONFIG[sourceType || 'unknown'] || SOURCE_TYPE_CONFIG.unknown;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 bg-surface rounded text-xs font-theme-data ${config.color}`}
    >
      <span>{config.icon}</span>
      <span>{config.label}</span>
    </span>
  );
}

export default SourceTypeBadge;
