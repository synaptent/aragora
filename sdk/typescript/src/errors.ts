/**
 * Aragora SDK Error Classes
 *
 * Custom error classes for handling API errors with structured information.
 * Mirrors the Python SDK's error hierarchy for consistency across SDKs.
 */

import type { ErrorCode, ApiError } from './types';

/**
 * Base error class for all Aragora SDK errors.
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.get('invalid-id');
 * } catch (error) {
 *   if (error instanceof AragoraError) {
 *     console.log(`Error: ${error.message}`);
 *     console.log(`Status: ${error.statusCode}`);
 *     console.log(`Trace ID: ${error.traceId}`);
 *   }
 * }
 * ```
 */
export class AragoraError extends Error {
  /** Human-readable error description */
  readonly message: string;
  /** HTTP status code, if applicable */
  readonly statusCode: number | undefined;
  /** Alias for statusCode - matches common error property naming */
  get status(): number | undefined {
    return this.statusCode;
  }
  /** Machine-readable error code from the API (e.g., "RATE_LIMITED") */
  readonly errorCode: ErrorCode | string | undefined;
  /** Alias for errorCode - matches API response field name */
  get code(): ErrorCode | string | undefined {
    return this.errorCode;
  }
  /** Unique request trace ID for debugging and support */
  readonly traceId: string | undefined;
  /** Raw parsed response body, if available */
  readonly responseBody: Record<string, unknown> | undefined;

  constructor(
    message: string,
    statusCode?: number,
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message);
    this.name = 'AragoraError';
    this.message = message;
    this.statusCode = statusCode;
    this.errorCode = errorCode;
    this.traceId = traceId;
    this.responseBody = responseBody;

    // Maintain proper prototype chain for instanceof checks
    Object.setPrototypeOf(this, new.target.prototype);
  }

  /**
   * Create an AragoraError from an HTTP response.
   */
  static fromResponse(status: number, body: ApiError): AragoraError {
    const responseBody = body as unknown as Record<string, unknown>;

    // Map to specialized error classes based on status code
    switch (status) {
      case 400:
        return new ValidationError(
          body.error,
          body.code,
          body.trace_id,
          responseBody
        );
      case 401:
        return new AuthenticationError(
          body.error,
          body.code,
          body.trace_id,
          responseBody
        );
      case 403:
        return new AuthorizationError(
          body.error,
          body.code,
          body.trace_id,
          responseBody
        );
      case 404:
        return new NotFoundError(
          body.error,
          body.code,
          body.trace_id,
          responseBody
        );
      case 429:
        return new RateLimitError(
          body.error,
          body.retry_after,
          body.code,
          body.trace_id,
          responseBody
        );
      default:
        if (status >= 500) {
          return new ServerError(
            body.error,
            status,
            body.code,
            body.trace_id,
            responseBody
          );
        }
        return new AragoraError(
          body.error,
          status,
          body.code,
          body.trace_id,
          responseBody
        );
    }
  }

  /**
   * Format the error as a string with all relevant information.
   */
  override toString(): string {
    let result = 'AragoraError';
    if (this.statusCode) {
      result += ` (${this.statusCode})`;
    }
    if (this.errorCode) {
      result += ` [${this.errorCode}]`;
    }
    result += `: ${this.message}`;
    if (this.traceId) {
      result += ` (trace: ${this.traceId})`;
    }
    return result;
  }
}

/**
 * Raised when authentication fails (401 errors).
 *
 * This error indicates that the request lacks valid authentication credentials.
 * Common causes include missing or invalid API keys.
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.list();
 * } catch (error) {
 *   if (error instanceof AuthenticationError) {
 *     console.log('Please check your API key');
 *   }
 * }
 * ```
 */
export class AuthenticationError extends AragoraError {
  constructor(
    message: string = 'Authentication failed',
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, 401, errorCode, traceId, responseBody);
    this.name = 'AuthenticationError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when authorization fails (403 errors).
 *
 * This error indicates that the authenticated user does not have permission
 * to access the requested resource.
 *
 * @example
 * ```typescript
 * try {
 *   await client.admin.getStats();
 * } catch (error) {
 *   if (error instanceof AuthorizationError) {
 *     console.log('You do not have permission to access this resource');
 *   }
 * }
 * ```
 */
export class AuthorizationError extends AragoraError {
  constructor(
    message: string = 'Access denied',
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, 403, errorCode, traceId, responseBody);
    this.name = 'AuthorizationError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when a resource is not found (404 errors).
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.get('non-existent-id');
 * } catch (error) {
 *   if (error instanceof NotFoundError) {
 *     console.log('Debate not found');
 *   }
 * }
 * ```
 */
export class NotFoundError extends AragoraError {
  constructor(
    message: string = 'Resource not found',
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, 404, errorCode, traceId, responseBody);
    this.name = 'NotFoundError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when rate limits are exceeded (429 errors).
 *
 * This error includes a `retryAfter` property indicating how many seconds
 * to wait before retrying the request.
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.create({ task: 'Test' });
 * } catch (error) {
 *   if (error instanceof RateLimitError) {
 *     console.log(`Rate limited. Retry after ${error.retryAfter} seconds`);
 *     await sleep(error.retryAfter * 1000);
 *     // Retry the request
 *   }
 * }
 * ```
 */
export class RateLimitError extends AragoraError {
  /** Number of seconds to wait before retrying */
  readonly retryAfter: number | undefined;

  constructor(
    message: string = 'Rate limit exceeded',
    retryAfter?: number,
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, 429, errorCode, traceId, responseBody);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
    Object.setPrototypeOf(this, new.target.prototype);
  }

  override toString(): string {
    let result = 'RateLimitError';
    if (this.statusCode) {
      result += ` (${this.statusCode})`;
    }
    if (this.errorCode) {
      result += ` [${this.errorCode}]`;
    }
    result += `: ${this.message}`;
    if (this.retryAfter) {
      result += ` (retry after ${this.retryAfter}s)`;
    }
    if (this.traceId) {
      result += ` (trace: ${this.traceId})`;
    }
    return result;
  }
}

/**
 * Raised when request validation fails (400 errors).
 *
 * This error includes an `errors` array with detailed validation error information.
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.create({ task: '' }); // Invalid empty task
 * } catch (error) {
 *   if (error instanceof ValidationError) {
 *     for (const err of error.errors) {
 *       console.log(`Field ${err.field}: ${err.message}`);
 *     }
 *   }
 * }
 * ```
 */
export class ValidationError extends AragoraError {
  /** Array of validation errors with field-level details */
  readonly errors: Array<{ field?: string; message?: string; [key: string]: unknown }>;

  constructor(
    message: string = 'Validation failed',
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, 400, errorCode, traceId, responseBody);
    this.name = 'ValidationError';
    // Extract errors array from response body if present
    this.errors = (responseBody?.errors as Array<{ field?: string; message?: string }>) ?? [];
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised for server errors (5xx errors).
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.create({ task: 'Test' });
 * } catch (error) {
 *   if (error instanceof ServerError) {
 *     console.log('Server error occurred. Please try again later.');
 *     console.log(`Status: ${error.statusCode}`);
 *   }
 * }
 * ```
 */
export class ServerError extends AragoraError {
  constructor(
    message: string = 'Server error',
    statusCode: number = 500,
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, statusCode, errorCode, traceId, responseBody);
    this.name = 'ServerError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when a request times out.
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.create({ task: 'Complex analysis' });
 * } catch (error) {
 *   if (error instanceof TimeoutError) {
 *     console.log('Request timed out. Consider increasing the timeout.');
 *   }
 * }
 * ```
 */
export class TimeoutError extends AragoraError {
  constructor(
    message: string = 'Request timed out',
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>
  ) {
    super(message, undefined, errorCode, traceId, responseBody);
    this.name = 'TimeoutError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when a connection cannot be established.
 *
 * @example
 * ```typescript
 * try {
 *   await client.debates.list();
 * } catch (error) {
 *   if (error instanceof ConnectionError) {
 *     console.log('Could not connect to the server. Check your network.');
 *   }
 * }
 * ```
 */
export class ConnectionError extends AragoraError {
  constructor(
    message: string = 'Connection failed',
    errorCode?: ErrorCode | string,
    traceId?: string,
    responseBody?: Record<string, unknown>,
    /** Retry eligibility, not automatic retry or guaranteed stream replay. */
    readonly retryable: boolean = true
  ) {
    super(message, undefined, errorCode, traceId, responseBody);
    this.name = 'ConnectionError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Check if an error is an Aragora API error.
 */
export function isAragoraError(error: unknown): error is AragoraError {
  return error instanceof AragoraError;
}

/**
 * Check if an error is a rate limit error.
 */
export function isRateLimitError(error: unknown): error is RateLimitError {
  return error instanceof RateLimitError;
}

/**
 * Check if an error is a validation error.
 */
export function isValidationError(error: unknown): error is ValidationError {
  return error instanceof ValidationError;
}

/**
 * Check if an error is retryable (server errors, timeouts, connection errors).
 */
export function isRetryableError(error: unknown): boolean {
  if (error instanceof ServerError) return true;
  if (error instanceof TimeoutError) return true;
  if (error instanceof ConnectionError) return error.retryable;
  if (error instanceof RateLimitError) return true;
  return false;
}
