export const RETURN_URL_STORAGE_KEY = 'aragora_return_url';
export const DEFAULT_RETURN_URL = '/';

const BLOCKED_PREFIXES = ['/auth/callback', '/auth/login', '/login', '/signup'];

function hasBlockedPrefix(path: string): boolean {
  return BLOCKED_PREFIXES.some(
    (prefix) => path === prefix || path.startsWith(`${prefix}?`) || path.startsWith(`${prefix}/`),
  );
}

/**
 * Ensure redirect paths are local app paths and avoid auth-loop destinations.
 */
export function normalizeReturnUrl(
  raw: string | null | undefined,
  fallback: string = DEFAULT_RETURN_URL,
): string {
  if (!raw) return fallback;

  const candidate = raw.trim();
  if (!candidate) return fallback;
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return fallback;
  if (candidate.includes('://')) return fallback;
  if (hasBlockedPrefix(candidate)) return fallback;
  return candidate;
}

export function getCurrentReturnUrl(fallback: string = DEFAULT_RETURN_URL): string {
  if (typeof window === 'undefined') return fallback;
  return normalizeReturnUrl(`${window.location.pathname}${window.location.search}`, fallback);
}
