/**
 * Aragora SDK HTTP Client
 *
 * Core HTTP client and error handling for the Aragora SDK.
 */

import type { AragoraClientConfig, RequestOptions } from './types';

// =============================================================================
// Error Class
// =============================================================================

export class AragoraError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;

  constructor(message: string, code: string, status: number, details?: Record<string, unknown>) {
    super(message);
    this.name = 'AragoraError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** Create a user-friendly error message */
  toUserMessage(): string {
    switch (this.code) {
      case 'TIMEOUT':
        return 'Request timed out. Please try again or check your network connection.';
      case 'NETWORK_ERROR':
        return 'Network error. Please check your internet connection and try again.';
      case 'RATE_LIMITED':
        return 'Too many requests. Please wait a moment before trying again.';
      case 'UNAUTHORIZED':
        return 'Authentication failed. Please sign in again.';
      case 'FORBIDDEN':
        return 'Access denied. You do not have permission to perform this action.';
      case 'NOT_FOUND':
        return 'The requested resource was not found.';
      default:
        return this.message;
    }
  }
}

// =============================================================================
// HTTP Client
// =============================================================================

export class HttpClient {
  private _baseUrl: string;
  private _apiKey?: string;
  private timeout: number;
  private defaultHeaders: Record<string, string>;

  get baseUrl(): string {
    return this._baseUrl;
  }

  get apiKey(): string | undefined {
    return this._apiKey;
  }

  constructor(config: AragoraClientConfig) {
    this._baseUrl = config.baseUrl.replace(/\/$/, '');
    this._apiKey = config.apiKey;
    this.timeout = config.timeout ?? 30000;
    this.defaultHeaders = { 'Content-Type': 'application/json', ...config.headers };

    if (this._apiKey) {
      this.defaultHeaders['Authorization'] = `Bearer ${this._apiKey}`;
    }
  }

  private async request<T>(
    method: string,
    path: string,
    data?: unknown,
    options?: RequestOptions,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options?.timeout ?? this.timeout);

    try {
      const response = await fetch(url, {
        method,
        headers: { ...this.defaultHeaders, ...options?.headers },
        body: data ? JSON.stringify(data) : undefined,
        signal: options?.signal ?? controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new AragoraError(
          errorData.error || `HTTP ${response.status}`,
          errorData.code || 'HTTP_ERROR',
          response.status,
          errorData,
        );
      }

      return response.json();
    } catch (error) {
      clearTimeout(timeoutId);

      if (error instanceof AragoraError) {
        throw error;
      }

      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          throw new AragoraError('Request timed out', 'TIMEOUT', 408);
        }
        throw new AragoraError(error.message, 'NETWORK_ERROR', 0);
      }

      throw new AragoraError('Unknown error', 'UNKNOWN_ERROR', 0);
    }
  }

  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('GET', path, undefined, options);
  }

  async post<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>('POST', path, data, options);
  }

  async put<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>('PUT', path, data, options);
  }

  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('DELETE', path, undefined, options);
  }

  async patch<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>('PATCH', path, data, options);
  }
}
