/**
 * API utility functions for making requests to the Aragora backend.
 */

// Use centralized config for correct production URL resolution
import { API_BASE_URL } from '@/config';
import { getRuntimeBackendConfig } from '@/lib/runtimeBackend';

const TOKENS_KEY = 'aragora_tokens';

/** Read the access token from localStorage (same key used by AuthContext). */
function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(TOKENS_KEY);
  if (!stored) return null;
  try {
    return (JSON.parse(stored) as { access_token?: string }).access_token || null;
  } catch {
    return null;
  }
}

interface ApiFetchOptions extends RequestInit {
  baseUrl?: string;
}

interface ApiFetchResult<T = unknown> {
  data?: T;
  error?: string;
}

function resolveApiBaseUrl(baseUrl?: string): string {
  if (baseUrl !== undefined) return baseUrl.replace(/\/$/, '');
  if (typeof window !== 'undefined') {
    return getRuntimeBackendConfig().config.api.replace(/\/$/, '');
  }
  return API_BASE_URL.replace(/\/$/, '');
}

function resolveRequestUrl(path: string, baseUrl?: string): string {
  const resolvedBaseUrl = resolveApiBaseUrl(baseUrl);
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  if (!resolvedBaseUrl) {
    return path.startsWith('/') ? path : `/${path}`;
  }
  return path.startsWith('/') ? `${resolvedBaseUrl}${path}` : `${resolvedBaseUrl}/${path}`;
}

/**
 * Fetch wrapper with standard configuration and error handling.
 *
 * @param path - API endpoint path (can be relative like '/api/debates' or full URL)
 * @param options - Fetch options including optional baseUrl override
 * @returns The JSON response data
 * @throws Error if the request fails
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { baseUrl, ...fetchOptions } = options;
  const url = resolveRequestUrl(path, baseUrl);

  // Set default headers and inject auth token when available
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(fetchOptions.headers as Record<string, string>),
  };
  const token = getAccessToken();
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...fetchOptions, headers });

  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    throw new Error(`API Error (${response.status}): ${errorText}`);
  }

  // Handle empty responses
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    return {} as T;
  }

  return response.json();
}

/**
 * Safe fetch wrapper that returns an object with either data or error.
 * Useful for components that want to handle errors without try/catch.
 *
 * @param path - API endpoint path
 * @param options - Fetch options
 * @returns Object with data or error field
 */
export async function apiFetchSafe<T = unknown>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<ApiFetchResult<T>> {
  try {
    const data = await apiFetch<T>(path, options);
    return { data };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

/**
 * GET request wrapper.
 */
export async function apiGet<T = unknown>(
  path: string,
  options: Omit<ApiFetchOptions, 'method'> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: 'GET' });
}

/**
 * POST request wrapper.
 */
export async function apiPost<T = unknown>(
  path: string,
  body?: unknown,
  options: Omit<ApiFetchOptions, 'method' | 'body'> = {},
): Promise<T> {
  return apiFetch<T>(path, {
    ...options,
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * PUT request wrapper.
 */
export async function apiPut<T = unknown>(
  path: string,
  body?: unknown,
  options: Omit<ApiFetchOptions, 'method' | 'body'> = {},
): Promise<T> {
  return apiFetch<T>(path, {
    ...options,
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * DELETE request wrapper.
 */
export async function apiDelete<T = unknown>(
  path: string,
  options: Omit<ApiFetchOptions, 'method'> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: 'DELETE' });
}
