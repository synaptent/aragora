'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import type { Endpoint } from './EndpointSelector';

const METHOD_COLORS: Record<string, string> = {
  GET: 'text-emerald-400',
  POST: 'text-blue-400',
  PUT: 'text-amber-400',
  DELETE: 'text-red-400',
  PATCH: 'text-purple-400',
};

interface ResponseData {
  status: number | null;
  data: unknown;
  error: string | null;
  duration: number;
  headers: Record<string, string>;
}

interface RequestBuilderProps {
  endpoint: Endpoint;
  onResponse: (response: ResponseData) => void;
}

const RATE_LIMIT_MAX = 10;
const RATE_LIMIT_WINDOW_MS = 60_000;

export function RequestBuilder({ endpoint, onResponse }: RequestBuilderProps) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
  const [apiKey, setApiKey] = useState('');
  const [body, setBody] = useState('');
  const [params, setParams] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [remaining, setRemaining] = useState(RATE_LIMIT_MAX);
  const timestampsRef = useRef<number[]>([]);

  useEffect(() => {
    setBody(endpoint.body ? JSON.stringify(endpoint.body, null, 2) : '');
    const paramDefaults: Record<string, string> = {};
    for (const p of endpoint.parameters || []) {
      paramDefaults[p.name] = p.default || '';
    }
    setParams(paramDefaults);
  }, [endpoint]);

  const buildUrl = useCallback(() => {
    let path = endpoint.path;
    const queryParts: string[] = [];

    for (const p of endpoint.parameters || []) {
      const val = params[p.name] || '';
      if (p.in === 'path') {
        path = path.replace(`{${p.name}}`, encodeURIComponent(val));
      } else if (p.in === 'query' && val) {
        queryParts.push(`${encodeURIComponent(p.name)}=${encodeURIComponent(val)}`);
      }
    }

    const qs = queryParts.length > 0 ? `?${queryParts.join('&')}` : '';
    return `${apiUrl}${path}${qs}`;
  }, [apiUrl, endpoint, params]);

  const checkRateLimit = useCallback(() => {
    const now = Date.now();
    timestampsRef.current = timestampsRef.current.filter((t) => now - t < RATE_LIMIT_WINDOW_MS);
    setRemaining(RATE_LIMIT_MAX - timestampsRef.current.length);
    return timestampsRef.current.length < RATE_LIMIT_MAX;
  }, []);

  const sendRequest = useCallback(async () => {
    if (!checkRateLimit()) return;

    timestampsRef.current.push(Date.now());
    setRemaining(RATE_LIMIT_MAX - timestampsRef.current.length);
    setLoading(true);

    const start = performance.now();
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`;
      }

      const init: RequestInit = { method: endpoint.method, headers };
      if (['POST', 'PUT', 'PATCH'].includes(endpoint.method) && body) {
        init.body = body;
      }

      const res = await fetch(buildUrl(), init);
      const duration = Math.round(performance.now() - start);

      const resHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        resHeaders[k] = v;
      });

      let data: unknown;
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('json')) {
        data = await res.json();
      } else {
        data = await res.text();
      }

      onResponse({ status: res.status, data, error: null, duration, headers: resHeaders });
    } catch (err) {
      const duration = Math.round(performance.now() - start);
      onResponse({
        status: null,
        data: null,
        error: err instanceof Error ? err.message : String(err),
        duration,
        headers: {},
      });
    } finally {
      setLoading(false);
    }
  }, [endpoint, body, apiKey, buildUrl, checkRateLimit, onResponse]);

  const hasBody = ['POST', 'PUT', 'PATCH'].includes(endpoint.method);
  const pathParams = (endpoint.parameters || []).filter((p) => p.in === 'path');
  const queryParams = (endpoint.parameters || []).filter((p) => p.in === 'query');

  return (
    <div className="p-4 space-y-3 bg-[var(--bg)]">
      {/* Method + URL */}
      <div className="flex items-center gap-2">
        <span
          className={`text-xs font-theme-data font-bold px-2 py-1 bg-[var(--surface)] ${METHOD_COLORS[endpoint.method] || ''}`}
        >
          {endpoint.method}
        </span>
        <code className="flex-1 text-xs font-theme-data text-[var(--text-muted)] truncate">
          {buildUrl()}
        </code>
        <button
          onClick={sendRequest}
          disabled={loading || remaining <= 0}
          className="px-4 py-1.5 text-xs font-theme-data font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 disabled:opacity-40 transition-colors"
        >
          {loading ? 'SENDING...' : 'SEND'}
        </button>
      </div>

      {/* Rate limit indicator */}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1 bg-[var(--surface)] rounded overflow-hidden">
          <div
            className="h-full bg-[var(--acid-green)] transition-all"
            style={{ width: `${(remaining / RATE_LIMIT_MAX) * 100}%` }}
          />
        </div>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          {remaining}/{RATE_LIMIT_MAX} req/min
        </span>
      </div>

      {/* API Key */}
      <div>
        <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
          API Key (optional)
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Bearer token..."
          className="w-full mt-1 px-2 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]"
        />
      </div>

      {/* Path parameters */}
      {pathParams.length > 0 && (
        <div className="space-y-2">
          <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
            Path Parameters
          </label>
          {pathParams.map((p) => (
            <div key={p.name} className="flex items-center gap-2">
              <span className="text-xs font-theme-data text-[var(--acid-green)] w-24 shrink-0">
                {p.name}
              </span>
              <input
                type="text"
                value={params[p.name] || ''}
                onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}
                placeholder={p.description || p.name}
                className="flex-1 px-2 py-1 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]"
              />
            </div>
          ))}
        </div>
      )}

      {/* Query parameters */}
      {queryParams.length > 0 && (
        <div className="space-y-2">
          <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
            Query Parameters
          </label>
          {queryParams.map((p) => (
            <div key={p.name} className="flex items-center gap-2">
              <span className="text-xs font-theme-data text-[var(--text-muted)] w-24 shrink-0">
                {p.name}
              </span>
              <input
                type="text"
                value={params[p.name] || ''}
                onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}
                placeholder={p.default || p.name}
                className="flex-1 px-2 py-1 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]"
              />
            </div>
          ))}
        </div>
      )}

      {/* Request body */}
      {hasBody && (
        <div>
          <label className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
            Request Body (JSON)
          </label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full mt-1 px-2 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)] resize-y"
          />
        </div>
      )}
    </div>
  );
}
