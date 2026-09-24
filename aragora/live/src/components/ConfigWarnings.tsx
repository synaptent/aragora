'use client';

import { useState, useEffect } from 'react';
import { getEnvWarnings, IS_DEV_MODE, type EnvWarning } from '@/config';

interface ConfigWarningsProps {
  /** Whether to show warnings even in production (default: only dev mode) */
  showInProduction?: boolean;
  /** Whether the component can be dismissed */
  dismissable?: boolean;
}

/**
 * Displays configuration warnings when environment variables are missing.
 * By default, only shows in development mode to avoid confusing end users.
 *
 * @example
 * ```tsx
 * // In layout.tsx or a dashboard page
 * <ConfigWarnings />
 * ```
 */
export function ConfigWarnings({
  showInProduction = false,
  dismissable = true,
}: ConfigWarningsProps) {
  const [dismissed, setDismissed] = useState(false);
  const [warnings, setWarnings] = useState<EnvWarning[]>([]);

  useEffect(() => {
    // Only check on client side
    if (typeof window !== 'undefined') {
      setWarnings(getEnvWarnings());
    }
  }, []);

  // Don't show if no warnings
  if (warnings.length === 0) return null;

  // Don't show in production unless explicitly requested
  if (!IS_DEV_MODE && !showInProduction) return null;

  // Don't show if dismissed
  if (dismissed) return null;

  return (
    <div className="fixed bottom-4 right-4 max-w-sm z-50">
      <div className="bg-surface border border-yellow-500/50 rounded-lg shadow-lg overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 bg-yellow-900/20 border-b border-yellow-500/30">
          <span className="text-xs font-medium text-yellow-400 flex items-center gap-2">
            <span>!</span>
            Configuration Warnings
          </span>
          {dismissable && (
            <button
              onClick={() => setDismissed(true)}
              className="text-yellow-400 hover:text-yellow-300 text-xs"
              aria-label="Dismiss warnings"
            >
              [DISMISS]
            </button>
          )}
        </div>
        <div className="p-3 space-y-2">
          {warnings.map((warning) => (
            <div key={warning.key} className="text-xs font-theme-data text-text-muted">
              <span className={warning.severity === 'error' ? 'text-red-400' : 'text-yellow-500'}>
                {warning.severity === 'error' ? '!' : '*'}
              </span>{' '}
              <span className="text-text">{warning.key}:</span> {warning.message}
            </div>
          ))}
        </div>
        {IS_DEV_MODE && (
          <div className="px-3 py-2 bg-surface-hover border-t border-border text-xs text-text-muted">
            Running in development mode
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Hook to get environment warnings for custom display.
 */
export function useConfigWarnings() {
  const [warnings, setWarnings] = useState<EnvWarning[]>([]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setWarnings(getEnvWarnings());
    }
  }, []);

  return {
    warnings,
    hasWarnings: warnings.length > 0,
    hasErrors: warnings.some((w) => w.severity === 'error'),
    isDevMode: IS_DEV_MODE,
  };
}
