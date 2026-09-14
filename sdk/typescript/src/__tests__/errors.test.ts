/**
 * Aragora SDK Error Classes Tests
 */

import { describe, it, expect } from 'vitest';
import {
  AragoraError,
  AuthenticationError,
  AuthorizationError,
  NotFoundError,
  RateLimitError,
  ValidationError,
  ServerError,
  TimeoutError,
  ConnectionError,
  isAragoraError,
  isRateLimitError,
  isValidationError,
  isRetryableError,
} from '../errors';
import type { ApiError } from '../types';

describe('AragoraError', () => {
  describe('constructor', () => {
    it('should create error with message only', () => {
      const error = new AragoraError('Something went wrong');
      expect(error.message).toBe('Something went wrong');
      expect(error.statusCode).toBeUndefined();
      expect(error.errorCode).toBeUndefined();
      expect(error.traceId).toBeUndefined();
      expect(error.responseBody).toBeUndefined();
      expect(error.name).toBe('AragoraError');
    });

    it('should create error with all parameters', () => {
      const responseBody = { error: 'Test', extra: 'data' };
      const error = new AragoraError(
        'Something went wrong',
        500,
        'INTERNAL_ERROR',
        'trace-123',
        responseBody
      );
      expect(error.message).toBe('Something went wrong');
      expect(error.statusCode).toBe(500);
      expect(error.errorCode).toBe('INTERNAL_ERROR');
      expect(error.traceId).toBe('trace-123');
      expect(error.responseBody).toEqual(responseBody);
    });

    it('should extend Error', () => {
      const error = new AragoraError('Test');
      expect(error).toBeInstanceOf(Error);
    });
  });

  describe('toString', () => {
    it('should format error with all fields', () => {
      const error = new AragoraError(
        'Something went wrong',
        500,
        'INTERNAL_ERROR',
        'trace-123'
      );
      expect(error.toString()).toBe(
        'AragoraError (500) [INTERNAL_ERROR]: Something went wrong (trace: trace-123)'
      );
    });

    it('should format error without optional fields', () => {
      const error = new AragoraError('Something went wrong');
      expect(error.toString()).toBe('AragoraError: Something went wrong');
    });

    it('should format error with status only', () => {
      const error = new AragoraError('Something went wrong', 404);
      expect(error.toString()).toBe('AragoraError (404): Something went wrong');
    });
  });

  describe('fromResponse', () => {
    it('should create AuthenticationError for 401', () => {
      const body: ApiError = {
        error: 'Invalid API key',
        code: 'INVALID_TOKEN',
        trace_id: 'trace-401',
      };
      const error = AragoraError.fromResponse(401, body);
      expect(error).toBeInstanceOf(AuthenticationError);
      expect(error.statusCode).toBe(401);
      expect(error.message).toBe('Invalid API key');
      expect(error.errorCode).toBe('INVALID_TOKEN');
      expect(error.traceId).toBe('trace-401');
    });

    it('should create AuthorizationError for 403', () => {
      const body: ApiError = {
        error: 'Access denied',
        code: 'FORBIDDEN',
        trace_id: 'trace-403',
      };
      const error = AragoraError.fromResponse(403, body);
      expect(error).toBeInstanceOf(AuthorizationError);
      expect(error.statusCode).toBe(403);
    });

    it('should create NotFoundError for 404', () => {
      const body: ApiError = {
        error: 'Debate not found',
        code: 'NOT_FOUND',
      };
      const error = AragoraError.fromResponse(404, body);
      expect(error).toBeInstanceOf(NotFoundError);
      expect(error.statusCode).toBe(404);
    });

    it('should create RateLimitError for 429 with retry_after', () => {
      const body: ApiError = {
        error: 'Rate limit exceeded',
        code: 'RATE_LIMITED',
        retry_after: 60,
      };
      const error = AragoraError.fromResponse(429, body);
      expect(error).toBeInstanceOf(RateLimitError);
      expect(error.statusCode).toBe(429);
      expect((error as RateLimitError).retryAfter).toBe(60);
    });

    it('should create ValidationError for 400', () => {
      const body: ApiError = {
        error: 'Validation failed',
        code: 'INVALID_VALUE',
      };
      const error = AragoraError.fromResponse(400, body);
      expect(error).toBeInstanceOf(ValidationError);
      expect(error.statusCode).toBe(400);
    });

    it('should create ServerError for 500', () => {
      const body: ApiError = {
        error: 'Internal server error',
        code: 'INTERNAL_ERROR',
      };
      const error = AragoraError.fromResponse(500, body);
      expect(error).toBeInstanceOf(ServerError);
      expect(error.statusCode).toBe(500);
    });

    it('should create ServerError for 502', () => {
      const body: ApiError = {
        error: 'Bad gateway',
      };
      const error = AragoraError.fromResponse(502, body);
      expect(error).toBeInstanceOf(ServerError);
      expect(error.statusCode).toBe(502);
    });

    it('should create ServerError for 503', () => {
      const body: ApiError = {
        error: 'Service unavailable',
        code: 'SERVICE_UNAVAILABLE',
      };
      const error = AragoraError.fromResponse(503, body);
      expect(error).toBeInstanceOf(ServerError);
      expect(error.statusCode).toBe(503);
    });

    it('should create base AragoraError for unknown status codes', () => {
      const body: ApiError = {
        error: 'Unknown error',
      };
      const error = AragoraError.fromResponse(418, body);
      expect(error).toBeInstanceOf(AragoraError);
      expect(error.constructor).toBe(AragoraError); // Not a subclass
      expect(error.statusCode).toBe(418);
    });
  });
});

describe('AuthenticationError', () => {
  it('should use default message', () => {
    const error = new AuthenticationError();
    expect(error.message).toBe('Authentication failed');
    expect(error.statusCode).toBe(401);
    expect(error.name).toBe('AuthenticationError');
  });

  it('should use custom message', () => {
    const error = new AuthenticationError('Invalid credentials');
    expect(error.message).toBe('Invalid credentials');
    expect(error.statusCode).toBe(401);
  });

  it('should be instanceof AragoraError', () => {
    const error = new AuthenticationError();
    expect(error).toBeInstanceOf(AragoraError);
    expect(error).toBeInstanceOf(AuthenticationError);
  });
});

describe('AuthorizationError', () => {
  it('should use default message', () => {
    const error = new AuthorizationError();
    expect(error.message).toBe('Access denied');
    expect(error.statusCode).toBe(403);
    expect(error.name).toBe('AuthorizationError');
  });

  it('should be instanceof AragoraError', () => {
    const error = new AuthorizationError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('NotFoundError', () => {
  it('should use default message', () => {
    const error = new NotFoundError();
    expect(error.message).toBe('Resource not found');
    expect(error.statusCode).toBe(404);
    expect(error.name).toBe('NotFoundError');
  });

  it('should be instanceof AragoraError', () => {
    const error = new NotFoundError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('RateLimitError', () => {
  it('should use default message', () => {
    const error = new RateLimitError();
    expect(error.message).toBe('Rate limit exceeded');
    expect(error.statusCode).toBe(429);
    expect(error.retryAfter).toBeUndefined();
    expect(error.name).toBe('RateLimitError');
  });

  it('should store retryAfter value', () => {
    const error = new RateLimitError('Too many requests', 30);
    expect(error.retryAfter).toBe(30);
  });

  it('should format toString with retry_after', () => {
    const error = new RateLimitError('Rate limit exceeded', 60, 'RATE_LIMITED');
    expect(error.toString()).toContain('(retry after 60s)');
  });

  it('should be instanceof AragoraError', () => {
    const error = new RateLimitError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('ValidationError', () => {
  it('should use default message', () => {
    const error = new ValidationError();
    expect(error.message).toBe('Validation failed');
    expect(error.statusCode).toBe(400);
    expect(error.errors).toEqual([]);
    expect(error.name).toBe('ValidationError');
  });

  it('should extract errors from responseBody', () => {
    const responseBody = {
      error: 'Validation failed',
      errors: [
        { field: 'email', message: 'Invalid email format' },
        { field: 'name', message: 'Name is required' },
      ],
    };
    const error = new ValidationError(
      'Validation failed',
      'INVALID_VALUE',
      undefined,
      responseBody
    );
    expect(error.errors).toHaveLength(2);
    expect(error.errors[0]).toEqual({ field: 'email', message: 'Invalid email format' });
    expect(error.errors[1]).toEqual({ field: 'name', message: 'Name is required' });
  });

  it('should handle responseBody without errors array', () => {
    const error = new ValidationError('Validation failed', 'INVALID_VALUE', undefined, {
      error: 'Test',
    });
    expect(error.errors).toEqual([]);
  });

  it('should be instanceof AragoraError', () => {
    const error = new ValidationError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('ServerError', () => {
  it('should use default message and status', () => {
    const error = new ServerError();
    expect(error.message).toBe('Server error');
    expect(error.statusCode).toBe(500);
    expect(error.name).toBe('ServerError');
  });

  it('should accept custom status code', () => {
    const error = new ServerError('Gateway timeout', 504);
    expect(error.statusCode).toBe(504);
    expect(error.message).toBe('Gateway timeout');
  });

  it('should be instanceof AragoraError', () => {
    const error = new ServerError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('TimeoutError', () => {
  it('should use default message', () => {
    const error = new TimeoutError();
    expect(error.message).toBe('Request timed out');
    expect(error.statusCode).toBeUndefined();
    expect(error.name).toBe('TimeoutError');
  });

  it('should be instanceof AragoraError', () => {
    const error = new TimeoutError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('ConnectionError', () => {
  it.each([undefined, true, false])('honors retryable=%s without changing error metadata', (retryable) => {
    const error = new ConnectionError('closed', 'WS_CLOSE_4003', undefined, { code: 4003 }, retryable);
    expect(error.retryable).toBe(retryable ?? true);
    expect(isRetryableError(error)).toBe(retryable ?? true);
    expect(error.code).toBe('WS_CLOSE_4003');
    expect(error.responseBody).toEqual({ code: 4003 });
    expect(error.statusCode).toBeUndefined();
  });

  it('should use default message', () => {
    const error = new ConnectionError();
    expect(error.message).toBe('Connection failed');
    expect(error.statusCode).toBeUndefined();
    expect(error.name).toBe('ConnectionError');
  });

  it('should be instanceof AragoraError', () => {
    const error = new ConnectionError();
    expect(error).toBeInstanceOf(AragoraError);
  });
});

describe('Type guard functions', () => {
  describe('isAragoraError', () => {
    it('should return true for AragoraError', () => {
      expect(isAragoraError(new AragoraError('test'))).toBe(true);
    });

    it('should return true for subclasses', () => {
      expect(isAragoraError(new AuthenticationError())).toBe(true);
      expect(isAragoraError(new RateLimitError())).toBe(true);
      expect(isAragoraError(new ValidationError())).toBe(true);
    });

    it('should return false for regular Error', () => {
      expect(isAragoraError(new Error('test'))).toBe(false);
    });

    it('should return false for non-errors', () => {
      expect(isAragoraError('error')).toBe(false);
      expect(isAragoraError(null)).toBe(false);
      expect(isAragoraError(undefined)).toBe(false);
      expect(isAragoraError({})).toBe(false);
    });
  });

  describe('isRateLimitError', () => {
    it('should return true for RateLimitError', () => {
      expect(isRateLimitError(new RateLimitError())).toBe(true);
    });

    it('should return false for other Aragora errors', () => {
      expect(isRateLimitError(new AragoraError('test'))).toBe(false);
      expect(isRateLimitError(new ServerError())).toBe(false);
    });
  });

  describe('isValidationError', () => {
    it('should return true for ValidationError', () => {
      expect(isValidationError(new ValidationError())).toBe(true);
    });

    it('should return false for other Aragora errors', () => {
      expect(isValidationError(new AragoraError('test'))).toBe(false);
      expect(isValidationError(new AuthenticationError())).toBe(false);
    });
  });

  describe('isRetryableError', () => {
    it('should return true for ServerError', () => {
      expect(isRetryableError(new ServerError())).toBe(true);
    });

    it('should return true for TimeoutError', () => {
      expect(isRetryableError(new TimeoutError())).toBe(true);
    });

    it('should return true for ConnectionError', () => {
      expect(isRetryableError(new ConnectionError())).toBe(true);
    });

    it('should return true for RateLimitError', () => {
      expect(isRetryableError(new RateLimitError())).toBe(true);
    });

    it('should return false for client errors', () => {
      expect(isRetryableError(new AuthenticationError())).toBe(false);
      expect(isRetryableError(new AuthorizationError())).toBe(false);
      expect(isRetryableError(new NotFoundError())).toBe(false);
      expect(isRetryableError(new ValidationError())).toBe(false);
    });

    it('should return false for base AragoraError', () => {
      expect(isRetryableError(new AragoraError('test'))).toBe(false);
    });

    it('should return false for regular Error', () => {
      expect(isRetryableError(new Error('test'))).toBe(false);
    });
  });
});

describe('Error inheritance chain', () => {
  it('AuthenticationError should be caught by AragoraError', () => {
    const error = new AuthenticationError();
    let caught = false;
    try {
      throw error;
    } catch (e) {
      if (e instanceof AragoraError) {
        caught = true;
      }
    }
    expect(caught).toBe(true);
  });

  it('all specialized errors should be instanceof AragoraError', () => {
    const errors = [
      new AuthenticationError(),
      new AuthorizationError(),
      new NotFoundError(),
      new RateLimitError(),
      new ValidationError(),
      new ServerError(),
      new TimeoutError(),
      new ConnectionError(),
    ];

    for (const error of errors) {
      expect(error).toBeInstanceOf(AragoraError);
      expect(error).toBeInstanceOf(Error);
    }
  });

  it('all specialized errors should have correct names', () => {
    expect(new AuthenticationError().name).toBe('AuthenticationError');
    expect(new AuthorizationError().name).toBe('AuthorizationError');
    expect(new NotFoundError().name).toBe('NotFoundError');
    expect(new RateLimitError().name).toBe('RateLimitError');
    expect(new ValidationError().name).toBe('ValidationError');
    expect(new ServerError().name).toBe('ServerError');
    expect(new TimeoutError().name).toBe('TimeoutError');
    expect(new ConnectionError().name).toBe('ConnectionError');
  });
});
