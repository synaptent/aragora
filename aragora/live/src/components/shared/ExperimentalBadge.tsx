'use client';

import { type FeatureStatus } from '@/lib/featureFlags';

interface ExperimentalBadgeProps {
  /** Feature status to display */
  status: FeatureStatus;
  /** Optional size variant */
  size?: 'sm' | 'md';
  /** Optional additional CSS classes */
  className?: string;
}

const STATUS_CONFIG: Record<FeatureStatus, { label: string; colors: string; tooltip: string }> = {
  stable: {
    label: 'STABLE',
    colors: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    tooltip: 'This feature is production-ready and fully supported.',
  },
  beta: {
    label: 'BETA',
    colors: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40',
    tooltip: 'This feature is mostly complete but may have minor issues. Feedback welcome!',
  },
  alpha: {
    label: 'ALPHA',
    colors: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    tooltip: 'This feature is experimental and may change significantly. Use with caution.',
  },
  deprecated: {
    label: 'DEPRECATED',
    colors: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    tooltip: 'This feature is deprecated and will be removed in a future version.',
  },
};

/**
 * Badge component to indicate feature maturity status
 *
 * @example
 * <ExperimentalBadge status="beta" />
 *
 * @example
 * <ExperimentalBadge status="alpha" size="sm" />
 */
export function ExperimentalBadge({ status, size = 'md', className = '' }: ExperimentalBadgeProps) {
  const config = STATUS_CONFIG[status];

  if (status === 'stable') {
    // Don't show badge for stable features
    return null;
  }

  const sizeClasses = size === 'sm' ? 'text-[8px] px-1 py-0.5' : 'text-[10px] px-1.5 py-0.5';

  return (
    <span
      className={`inline-flex items-center font-theme-data font-bold border rounded ${config.colors} ${sizeClasses} ${className}`}
      title={config.tooltip}
    >
      {config.label}
    </span>
  );
}

/**
 * Inline variant for use in text
 */
export function ExperimentalTag({ status }: { status: FeatureStatus }) {
  if (status === 'stable') return null;

  const config = STATUS_CONFIG[status];

  return (
    <span
      className={`text-[10px] font-theme-data ${config.colors.split(' ')[1]} ml-1`}
      title={config.tooltip}
    >
      [{config.label}]
    </span>
  );
}

/**
 * Banner variant for feature sections
 */
export function ExperimentalBanner({
  status,
  featureName,
}: {
  status: FeatureStatus;
  featureName: string;
}) {
  if (status === 'stable') return null;

  const config = STATUS_CONFIG[status];

  return (
    <div className={`px-3 py-2 border ${config.colors} mb-4`}>
      <div className="flex items-center gap-2">
        <ExperimentalBadge status={status} size="sm" />
        <span className="text-xs font-theme-data">{featureName}</span>
      </div>
      <p className="text-[10px] font-theme-data text-text-muted mt-1">{config.tooltip}</p>
    </div>
  );
}
