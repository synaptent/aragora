'use client';

import { useCallback, useRef } from 'react';
import { useToastContext } from '@/context/ToastContext';
import { logger } from '@/utils/logger';

/**
 * Error classification for user-friendly messages
 */
type ErrorType = 'network' | 'auth' | 'validation' | 'server' | 'timeout' | 'unknown';

interface ErrorHandlerOptions {
  /** Show toast notification (default: true) */
  showToast?: boolean;
  /** Toast duration in ms (default: 5000) */
  duration?: number;
  /** Log to console (default: true in dev) */
  logToConsole?: boolean;
  /** Custom error message override */
  customMessage?: string;
  /** Retry callback */
  onRetry?: () => void | Promise<void>;
}

interface UseErrorHandlerReturn {
  /** Handle any error with automatic classification and toast */
  handleError: (error: unknown, options?: ErrorHandlerOptions) => void;
  /** Handle async operations with error handling */
  handleAsync: <T>(
    fn: () => Promise<T>,
    options?: ErrorHandlerOptions & { onSuccess?: (result: T) => void },
  ) => Promise<T | undefined>;
  /** Wrap a function with error handling */
  withErrorHandling: <T extends (...args: Parameters<T>) => Promise<ReturnType<T>>>(
    fn: T,
    options?: ErrorHandlerOptions,
  ) => (...args: Parameters<T>) => Promise<ReturnType<T> | undefined>;
  /** Last error (for UI display) */
  lastError: Error | null;
  /** Clear last error */
  clearError: () => void;
}

/**
 * Classify error type from error object
 */
function classifyError(error: unknown): ErrorType {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    const name = error.name.toLowerCase();

    // Network errors
    if (
      (name === 'typeerror' && message.includes('fetch')) ||
      message.includes('network') ||
      message.includes('connection') ||
      message.includes('cors') ||
      message.includes('econnrefused')
    ) {
      return 'network';
    }

    // Auth errors
    if (
      message.includes('unauthorized') ||
      message.includes('forbidden') ||
      message.includes('401') ||
      message.includes('403') ||
      message.includes('authentication')
    ) {
      return 'auth';
    }

    // Validation errors
    if (
      message.includes('validation') ||
      message.includes('invalid') ||
      message.includes('required') ||
      message.includes('400')
    ) {
      return 'validation';
    }

    // Server errors
    if (
      message.includes('500') ||
      message.includes('502') ||
      message.includes('503') ||
      message.includes('server error')
    ) {
      return 'server';
    }

    // Timeout
    if (name === 'aborterror' || message.includes('timeout') || message.includes('aborted')) {
      return 'timeout';
    }
  }

  return 'unknown';
}

/**
 * Get user-friendly message based on error type
 */
function getUserFriendlyMessage(error: unknown, errorType: ErrorType): string {
  switch (errorType) {
    case 'network':
      return 'Connection failed. Please check your network and try again.';
    case 'auth':
      return 'Authentication required. Please log in and try again.';
    case 'validation':
      return error instanceof Error ? error.message : 'Invalid input. Please check your data.';
    case 'server':
      return 'Server error. Our team has been notified. Please try again later.';
    case 'timeout':
      return 'Request timed out. Please try again.';
    default:
      return error instanceof Error ? error.message : 'An unexpected error occurred.';
  }
}

/**
 * Unified error handling hook with toast notifications
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { handleError, handleAsync } = useErrorHandler();
 *
 *   // Handle errors manually
 *   try {
 *     await riskyOperation();
 *   } catch (e) {
 *     handleError(e, { customMessage: 'Failed to perform operation' });
 *   }
 *
 *   // Or use handleAsync for automatic handling
 *   const result = await handleAsync(
 *     () => fetchData(),
 *     { onSuccess: (data) => setData(data) }
 *   );
 * }
 * ```
 */
export function useErrorHandler(): UseErrorHandlerReturn {
  const { showError } = useToastContext();
  const lastErrorRef = useRef<Error | null>(null);

  const handleError = useCallback(
    (error: unknown, options: ErrorHandlerOptions = {}) => {
      const {
        showToast = true,
        duration = 5000,
        logToConsole = process.env.NODE_ENV === 'development',
        customMessage,
      } = options;

      // Convert to Error if needed
      const errorObj = error instanceof Error ? error : new Error(String(error));
      lastErrorRef.current = errorObj;

      // Classify and get message
      const errorType = classifyError(error);
      const message = customMessage || getUserFriendlyMessage(error, errorType);

      // Log to console
      if (logToConsole) {
        logger.error('[ErrorHandler]', {
          type: errorType,
          message: errorObj.message,
          stack: errorObj.stack,
          original: error,
        });
      }

      // Show toast
      if (showToast) {
        showError(message, duration);
      }
    },
    [showError],
  );

  const handleAsync = useCallback(
    async <T>(
      fn: () => Promise<T>,
      options: ErrorHandlerOptions & { onSuccess?: (result: T) => void } = {},
    ): Promise<T | undefined> => {
      try {
        const result = await fn();
        options.onSuccess?.(result);
        return result;
      } catch (error) {
        handleError(error, options);
        return undefined;
      }
    },
    [handleError],
  );

  const withErrorHandling = useCallback(
    <T extends (...args: Parameters<T>) => Promise<ReturnType<T>>>(
      fn: T,
      options: ErrorHandlerOptions = {},
    ) => {
      return async (...args: Parameters<T>): Promise<ReturnType<T> | undefined> => {
        try {
          return await fn(...args);
        } catch (error) {
          handleError(error, options);
          return undefined;
        }
      };
    },
    [handleError],
  );

  const clearError = useCallback(() => {
    lastErrorRef.current = null;
  }, []);

  return {
    handleError,
    handleAsync,
    withErrorHandling,
    get lastError() {
      return lastErrorRef.current;
    },
    clearError,
  };
}
