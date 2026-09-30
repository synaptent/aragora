/**
 * Base API class and HTTP client for Aragora SDK
 *
 * This module provides the foundation for all API classes.
 */

export class AragoraError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = 'AragoraError';
  }
}

export interface AragoraClientConfig {
  baseUrl: string;
  apiKey?: string;
  timeout?: number;
  retryEnabled?: boolean;
  maxRetries?: number;
}

export class HttpClient {
  readonly baseUrl: string;
  readonly apiKey?: string;
  private timeout: number;
  private retryEnabled: boolean;
  private maxRetries: number;

  constructor(config: AragoraClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, '');
    this.apiKey = config.apiKey;
    this.timeout = config.timeout ?? 30000;
    this.retryEnabled = config.retryEnabled ?? true;
    this.maxRetries = config.maxRetries ?? 3;
  }

  private buildHeaders(extra?: Record<string, string>): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...extra,
    };
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    extraHeaders?: Record<string, string>,
  ): Promise<T> {
    const url = path.startsWith('http') ? path : `${this.baseUrl}${path}`;
    const headers = this.buildHeaders(extraHeaders);

    let lastError: Error | null = null;
    const maxAttempts = this.retryEnabled ? this.maxRetries : 1;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        const response = await fetch(url, {
          method,
          headers,
          body: body ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          let errorData: { message?: string; error?: string; code?: string; details?: unknown } =
            {};
          try {
            errorData = await response.json();
          } catch {
            // Response body not JSON
          }

          const errorMessage = errorData.message || errorData.error || `HTTP ${response.status}`;
          throw new AragoraError(errorMessage, response.status, errorData.code, errorData.details);
        }

        // Handle empty responses
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          return {} as T;
        }

        const text = await response.text();
        if (!text) {
          return {} as T;
        }

        return JSON.parse(text) as T;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        // Don't retry client errors (4xx) except rate limiting
        if (
          error instanceof AragoraError &&
          error.status >= 400 &&
          error.status < 500 &&
          error.status !== 429
        ) {
          throw error;
        }

        // Retry on network errors and server errors
        if (attempt < maxAttempts) {
          await new Promise((resolve) => setTimeout(resolve, Math.pow(2, attempt) * 100));
          continue;
        }
      }
    }

    throw lastError || new Error('Request failed');
  }

  async get<T>(path: string, headers?: Record<string, string>): Promise<T> {
    return this.request<T>('GET', path, undefined, headers);
  }

  async post<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    return this.request<T>('POST', path, body, headers);
  }

  async put<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    return this.request<T>('PUT', path, body, headers);
  }

  async patch<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    return this.request<T>('PATCH', path, body, headers);
  }

  async delete<T>(path: string, headers?: Record<string, string>): Promise<T> {
    return this.request<T>('DELETE', path, undefined, headers);
  }
}

/**
 * Base class for all API modules.
 * Provides access to the HTTP client.
 */
export abstract class BaseAPI {
  protected readonly http: HttpClient;

  constructor(http: HttpClient) {
    this.http = http;
  }
}
