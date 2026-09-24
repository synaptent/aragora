'use client';

import React, { ReactNode } from 'react';
import { useFeatureStatus, useFeatureInfo } from '@/context/FeaturesContext';

interface FeatureGuardProps {
  /** ID of the feature to check */
  featureId: string;
  /** Content to render when feature is available */
  children: ReactNode;
  /** Optional custom fallback when feature is unavailable */
  fallback?: ReactNode;
  /** Hide completely instead of showing fallback */
  hideWhenUnavailable?: boolean;
}

/**
 * Guard component for conditional rendering based on feature availability
 *
 * Wraps content that depends on optional backend features and shows
 * helpful messages when features are unavailable.
 *
 * @example
 * // Basic usage
 * <FeatureGuard featureId="pulse">
 *   <TrendingTopicsPanel />
 * </FeatureGuard>
 *
 * // With custom fallback
 * <FeatureGuard
 *   featureId="memory"
 *   fallback={<div>Memory features coming soon</div>}
 * >
 *   <MemoryInspector />
 * </FeatureGuard>
 *
 * // Hide completely when unavailable
 * <FeatureGuard featureId="experimental" hideWhenUnavailable>
 *   <ExperimentalPanel />
 * </FeatureGuard>
 */
export function FeatureGuard({
  featureId,
  children,
  fallback,
  hideWhenUnavailable = false,
}: FeatureGuardProps) {
  const available = useFeatureStatus(featureId);

  if (available) {
    return <>{children}</>;
  }

  if (hideWhenUnavailable) {
    return null;
  }

  if (fallback) {
    return <>{fallback}</>;
  }

  return <FeatureUnavailable featureId={featureId} />;
}

interface FeatureUnavailableProps {
  featureId: string;
}

/**
 * Default fallback component for unavailable features
 *
 * Shows feature name and optional install hints from the backend.
 * Distinguishes between "requires configuration" and truly unavailable.
 */
function FeatureUnavailable({ featureId }: FeatureUnavailableProps) {
  const info = useFeatureInfo(featureId);

  // Check if feature requires configuration (vs truly missing)
  const requiresConfig =
    info?.reason?.toLowerCase().includes('requires configuration') ||
    info?.reason?.toLowerCase().includes('set ') ||
    info?.reason?.toLowerCase().includes('api key');

  const statusText = requiresConfig ? 'Requires Configuration' : 'Unavailable';

  const statusColor = requiresConfig
    ? 'text-blue-400 border-blue-500/30'
    : 'text-amber-400 border-amber-500/30';

  const bgColor = requiresConfig ? 'bg-blue-900/10' : 'bg-amber-900/10';

  return (
    <div className={`bg-surface border ${statusColor.split(' ')[1]} rounded-lg p-4`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`${statusColor.split(' ')[0]} text-lg`}>
          {requiresConfig ? '\u2699' : '!'}
        </span>
        <h3 className={`text-sm font-medium ${statusColor.split(' ')[0]}`}>
          {info?.name || featureId} {statusText}
        </h3>
      </div>
      <p className="text-xs text-text-muted mb-2">
        {info?.reason ||
          info?.description ||
          `The ${featureId} feature is not currently available.`}
      </p>
      {info?.install_hint && (
        <details className="mt-2" open={requiresConfig}>
          <summary className="text-xs text-text-muted cursor-pointer hover:text-text">
            {requiresConfig ? 'Configuration steps' : 'How to enable'}
          </summary>
          <p
            className={`mt-2 text-xs ${statusColor.split(' ')[0].replace('text-', 'text-')}/70 ${bgColor} p-2 rounded`}
          >
            {info.install_hint}
          </p>
        </details>
      )}
    </div>
  );
}

/**
 * HOC to wrap any component with FeatureGuard
 *
 * @example
 * const GuardedPulsePanel = withFeatureGuard(TrendingTopicsPanel, 'pulse');
 */
export function withFeatureGuard<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  featureId: string,
  options: { hideWhenUnavailable?: boolean } = {},
) {
  return function WithFeatureGuard(props: P) {
    return (
      <FeatureGuard featureId={featureId} hideWhenUnavailable={options.hideWhenUnavailable}>
        <WrappedComponent {...props} />
      </FeatureGuard>
    );
  };
}
