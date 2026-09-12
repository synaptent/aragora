/**
 * Cloudflare Pages Function: Proxy /api/* to api.aragora.ai
 *
 * Static exports can't use next.config.js rewrites, so this Pages Function
 * proxies all /api/ requests to the backend, preserving the path, query
 * string, method, headers, and body.
 */

const BACKEND_ORIGIN = 'https://api.aragora.ai';

// Headers that must not be forwarded to the backend
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'te',
  'trailer',
  'upgrade',
  'host',
]);

export const onRequest: PagesFunction = async (context) => {
  const url = new URL(context.request.url);

  // Build backend URL preserving path and query string
  const backendUrl = `${BACKEND_ORIGIN}${url.pathname}${url.search}`;

  // Forward request headers, excluding hop-by-hop
  const headers = new Headers();
  for (const [key, value] of context.request.headers) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  }
  headers.set('X-Forwarded-For', context.request.headers.get('cf-connecting-ip') || '');
  headers.set('X-Forwarded-Proto', 'https');

  const response = await fetch(backendUrl, {
    method: context.request.method,
    headers,
    body:
      context.request.method !== 'GET' && context.request.method !== 'HEAD'
        ? context.request.body
        : undefined,
  });

  // Build response, adding CORS for same-origin requests from the frontend
  const respHeaders = new Headers(response.headers);
  respHeaders.set('Access-Control-Allow-Origin', url.origin);
  respHeaders.set('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
  respHeaders.set('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With');
  respHeaders.set('Access-Control-Allow-Credentials', 'true');

  // Handle CORS preflight
  if (context.request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: respHeaders });
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: respHeaders,
  });
};
