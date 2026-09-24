/**
 * Development-only logging utility.
 *
 * In production, logs are suppressed to avoid leaking debug info.
 * Error boundaries still use console.error directly for critical errors.
 */

const isDev = process.env.NODE_ENV === 'development';

export const logger = {
  /**
   * Log debug info (dev only)
   */
  debug: (...args: unknown[]) => {
    if (isDev) console.log('[debug]', ...args);
  },

  /**
   * Log warnings (dev only)
   */
  warn: (...args: unknown[]) => {
    if (isDev) console.warn('[warn]', ...args);
  },

  /**
   * Log errors (dev only, for non-critical errors)
   * Critical errors in ErrorBoundary should use console.error directly.
   */
  error: (...args: unknown[]) => {
    if (isDev) console.error('[error]', ...args);
  },
};
