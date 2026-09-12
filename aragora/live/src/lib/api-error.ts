/**
 * Unified API Error Handling
 *
 * Provides consistent error handling across the application.
 * Re-exports AragoraError from the SDK and adds utility functions.
 */

// Re-export the main error class from the SDK
export { AragoraError } from './aragora-client';

/**
 * Standard error codes used across the API
 */
export const ErrorCodes = {
  // Network errors
  NETWORK_ERROR: 'NETWORK_ERROR',
  TIMEOUT: 'TIMEOUT',

  // Auth errors
  UNAUTHORIZED: 'UNAUTHORIZED',
  FORBIDDEN: 'FORBIDDEN',
  TOKEN_EXPIRED: 'TOKEN_EXPIRED',

  // Client errors
  BAD_REQUEST: 'BAD_REQUEST',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  CONFLICT: 'CONFLICT',

  // Rate limiting
  RATE_LIMITED: 'RATE_LIMITED',

  // Server errors
  SERVER_ERROR: 'SERVER_ERROR',
  SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',

  // Unknown
  UNKNOWN_ERROR: 'UNKNOWN_ERROR',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];

/**
 * Map HTTP status codes to error codes
 */
export function statusToErrorCode(status: number): ErrorCode {
  switch (status) {
    case 400:
      return ErrorCodes.BAD_REQUEST;
    case 401:
      return ErrorCodes.UNAUTHORIZED;
    case 403:
      return ErrorCodes.FORBIDDEN;
    case 404:
      return ErrorCodes.NOT_FOUND;
    case 408:
      return ErrorCodes.TIMEOUT;
    case 409:
      return ErrorCodes.CONFLICT;
    case 422:
      return ErrorCodes.VALIDATION_ERROR;
    case 429:
      return ErrorCodes.RATE_LIMITED;
    case 500:
      return ErrorCodes.SERVER_ERROR;
    case 502:
    case 503:
    case 504:
      return ErrorCodes.SERVICE_UNAVAILABLE;
    default:
      return status >= 500 ? ErrorCodes.SERVER_ERROR : ErrorCodes.UNKNOWN_ERROR;
  }
}

/**
 * Get user-friendly error message based on error code
 */
export function getErrorMessage(code: ErrorCode, fallbackMessage?: string): string {
  switch (code) {
    case ErrorCodes.NETWORK_ERROR:
      return 'Unable to connect. Please check your internet connection.';
    case ErrorCodes.TIMEOUT:
      return 'Request timed out. Please try again.';
    case ErrorCodes.UNAUTHORIZED:
      return 'Session expired. Please sign in again.';
    case ErrorCodes.FORBIDDEN:
      return 'You do not have permission to perform this action.';
    case ErrorCodes.TOKEN_EXPIRED:
      return 'Your session has expired. Please sign in again.';
    case ErrorCodes.BAD_REQUEST:
      return fallbackMessage || 'Invalid request. Please check your input.';
    case ErrorCodes.VALIDATION_ERROR:
      return fallbackMessage || 'Validation failed. Please check your input.';
    case ErrorCodes.NOT_FOUND:
      return 'The requested resource was not found.';
    case ErrorCodes.CONFLICT:
      return 'A conflict occurred. The resource may have been modified.';
    case ErrorCodes.RATE_LIMITED:
      return 'Too many requests. Please wait a moment and try again.';
    case ErrorCodes.SERVER_ERROR:
      return 'An unexpected error occurred. Please try again later.';
    case ErrorCodes.SERVICE_UNAVAILABLE:
      return 'Service temporarily unavailable. Please try again later.';
    default:
      return fallbackMessage || 'An unexpected error occurred.';
  }
}

/**
 * Create an error from a fetch Response object
 */
export async function createErrorFromResponse(response: Response): Promise<Error> {
  const { AragoraError } = await import('./aragora-client');

  let errorData: Record<string, unknown> = {};
  let message = `Request failed: ${response.status}`;

  try {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      errorData = await response.json();
      message = (errorData.error as string) || (errorData.message as string) || message;
    } else {
      const text = await response.text();
      if (text) {
        message = text.slice(0, 200); // Limit length
      }
    }
  } catch {
    // Ignore parse errors
  }

  const code = (errorData.code as string) || statusToErrorCode(response.status);

  return new AragoraError(message, code, response.status, errorData);
}

/**
 * Check if an error is retryable (network issues, rate limiting, server errors)
 */
export function isRetryableError(error: unknown): boolean {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();

    // Network errors
    if (
      error.name === 'TypeError' ||
      message.includes('network') ||
      message.includes('fetch') ||
      message.includes('connection')
    ) {
      return true;
    }

    // Check AragoraError code/status
    if ('code' in error) {
      const code = (error as { code: string }).code;
      const retryableCodes: string[] = [
        ErrorCodes.NETWORK_ERROR,
        ErrorCodes.TIMEOUT,
        ErrorCodes.RATE_LIMITED,
        ErrorCodes.SERVICE_UNAVAILABLE,
      ];
      return retryableCodes.includes(code);
    }

    if ('status' in error) {
      const status = (error as { status: number }).status;
      // 429 (rate limit), 502-504 (gateway errors)
      return status === 429 || (status >= 502 && status <= 504);
    }
  }

  return false;
}

/**
 * Check if an error is an authentication error
 */
export function isAuthError(error: unknown): boolean {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();

    if (
      message.includes('unauthorized') ||
      message.includes('401') ||
      message.includes('authentication') ||
      message.includes('token expired')
    ) {
      return true;
    }

    if ('code' in error) {
      const code = (error as { code: string }).code;
      const authErrorCodes: string[] = [ErrorCodes.UNAUTHORIZED, ErrorCodes.TOKEN_EXPIRED];
      return authErrorCodes.includes(code);
    }

    if ('status' in error) {
      return (error as { status: number }).status === 401;
    }
  }

  return false;
}

/**
 * Get a user-friendly display string from any caught error value.
 *
 * Replaces the common `err instanceof Error ? err.message : 'Unknown error'`
 * pattern with richer type-aware messaging. Handles Error objects, fetch
 * TypeError ("Failed to fetch"), AbortError (timeouts), and non-Error values.
 */
export function getDisplayError(error: unknown, fallback = 'An unexpected error occurred'): string {
  if (error instanceof Error) {
    if (error.name === 'AbortError') {
      return 'Request timed out. Please try again.';
    }
    if (error.name === 'TypeError' && error.message === 'Failed to fetch') {
      return 'Cannot reach the server. Check your connection.';
    }
    // Use AragoraError code-based message if available
    if ('code' in error && typeof (error as { code: unknown }).code === 'string') {
      const code = (error as { code: string }).code as ErrorCode;
      const mapped = getErrorMessage(code);
      if (mapped !== fallback) return mapped;
    }
    return error.message || fallback;
  }
  if (typeof error === 'string' && error.length > 0) {
    return error;
  }
  return fallback;
}

/**
 * Extract error details for logging
 */
export function extractErrorDetails(error: unknown): {
  message: string;
  code?: string;
  status?: number;
  stack?: string;
} {
  if (error instanceof Error) {
    return {
      message: error.message,
      code: 'code' in error ? String((error as { code: unknown }).code) : undefined,
      status: 'status' in error ? Number((error as { status: unknown }).status) : undefined,
      stack: error.stack,
    };
  }

  return { message: String(error) };
}
