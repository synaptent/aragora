/**
 * OpenRouter OAuth PKCE utilities.
 *
 * Implements the client-side PKCE flow for obtaining an OpenRouter API key
 * without requiring users to manually copy-paste keys. No app registration
 * needed — OpenRouter accepts any callback URL.
 *
 * Flow:
 *   1. generateCodeVerifier() + generateCodeChallenge()
 *   2. Redirect to OpenRouter /auth with challenge
 *   3. User authorises and sets budget cap
 *   4. exchangeCodeForKey() with the returned code
 *   5. Receive a permanent sk-or-v1-... API key
 */

const OPENROUTER_AUTH_URL = 'https://openrouter.ai/auth';
const OPENROUTER_KEYS_API = 'https://openrouter.ai/api/v1/auth/keys';
const OPENROUTER_KEY_INFO_API = 'https://openrouter.ai/api/v1/auth/key';

export const SESSION_VERIFIER_KEY = 'openrouter_pkce_verifier';
export const SESSION_RETURN_KEY = 'openrouter_return_path';

// ---------------------------------------------------------------------------
// PKCE helpers
// ---------------------------------------------------------------------------

function base64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function generateCodeVerifier(): string {
  const bytes = new Uint8Array(64);
  crypto.getRandomValues(bytes);
  return base64url(bytes.buffer);
}

export async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(verifier));
  return base64url(digest);
}

// ---------------------------------------------------------------------------
// Auth flow
// ---------------------------------------------------------------------------

/**
 * Begin the OpenRouter OAuth PKCE flow.
 * Stores the code verifier in sessionStorage, then redirects the browser.
 */
export async function startOpenRouterAuth(callbackUrl: string): Promise<void> {
  const verifier = generateCodeVerifier();
  const challenge = await generateCodeChallenge(verifier);

  sessionStorage.setItem(SESSION_VERIFIER_KEY, verifier);
  sessionStorage.setItem(SESSION_RETURN_KEY, window.location.pathname);

  const params = new URLSearchParams({
    callback_url: callbackUrl,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });

  window.location.href = `${OPENROUTER_AUTH_URL}?${params.toString()}`;
}

export interface KeyExchangeResult {
  key: string;
  userId: string | null;
}

/**
 * Exchange an authorization code for an OpenRouter API key.
 * Reads the code verifier from sessionStorage (set by startOpenRouterAuth).
 */
export async function exchangeCodeForKey(code: string): Promise<KeyExchangeResult> {
  const verifier = sessionStorage.getItem(SESSION_VERIFIER_KEY);
  if (!verifier) {
    throw new Error('Missing PKCE code verifier. Please restart the connection flow.');
  }

  const res = await fetch(OPENROUTER_KEYS_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, code_verifier: verifier, code_challenge_method: 'S256' }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`OpenRouter key exchange failed (${res.status}): ${body || res.statusText}`);
  }

  const data = await res.json();

  // Clean up session storage
  sessionStorage.removeItem(SESSION_VERIFIER_KEY);

  return { key: data.key, userId: data.user_id ?? null };
}

// ---------------------------------------------------------------------------
// Key info
// ---------------------------------------------------------------------------

export interface OpenRouterKeyInfo {
  label: string | null;
  limit: number | null;
  limitRemaining: number | null;
  usage: number;
  rateLimit: { requests: number; interval: string } | null;
}

/**
 * Fetch usage and limit info for an OpenRouter API key.
 * Returns null on any failure (best-effort).
 */
export async function fetchKeyInfo(apiKey: string): Promise<OpenRouterKeyInfo | null> {
  try {
    const res = await fetch(OPENROUTER_KEY_INFO_API, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (!res.ok) return null;

    const data = await res.json();
    return {
      label: data.data?.label ?? null,
      limit: data.data?.limit ?? null,
      limitRemaining:
        data.data?.limit != null && data.data?.usage != null
          ? data.data.limit - data.data.usage
          : null,
      usage: data.data?.usage ?? 0,
      rateLimit: data.data?.rate_limit
        ? { requests: data.data.rate_limit.requests, interval: data.data.rate_limit.interval }
        : null,
    };
  } catch {
    return null;
  }
}
