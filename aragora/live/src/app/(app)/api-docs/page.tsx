'use client';

import { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { API_BASE_URL } from '@/config';

// ---- Types ----

interface OpenAPIParameter {
  name: string;
  in: string;
  required?: boolean;
  description?: string;
  schema?: { type?: string; enum?: string[] };
}

interface OpenAPIRequestBody {
  required?: boolean;
  content?: Record<string, { schema?: Record<string, unknown> }>;
}

interface OpenAPIResponse {
  description?: string;
  content?: Record<string, { schema?: Record<string, unknown> }>;
}

interface OpenAPIOperation {
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: OpenAPIParameter[];
  requestBody?: OpenAPIRequestBody;
  responses?: Record<string, OpenAPIResponse>;
  deprecated?: boolean;
  security?: Record<string, string[]>[];
}

interface OpenAPISpec {
  openapi: string;
  info: { title: string; version: string; description?: string };
  tags?: { name: string; description?: string }[];
  paths: Record<string, Record<string, OpenAPIOperation>>;
}

interface GroupedEndpoint {
  path: string;
  method: string;
  operation: OpenAPIOperation;
}

// ---- Constants ----

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40',
  POST: 'bg-blue-500/20 text-blue-400 border-blue-500/40',
  PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
  PATCH: 'bg-orange-500/20 text-orange-400 border-orange-500/40',
  DELETE: 'bg-red-500/20 text-red-400 border-red-500/40',
};

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

// ---- Component ----

export default function ApiDocsPage() {
  const [spec, setSpec] = useState<OpenAPISpec | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());

  // Fetch OpenAPI spec
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);

    fetch(`${API_BASE_URL}/api/v1/docs/openapi.json`, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: OpenAPISpec) => {
        setSpec(data);
        setError(null);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') {
          setError(e.message || 'Failed to load API spec');
        }
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, []);

  // Group endpoints by tag
  const { grouped, tags, methodCounts, totalEndpoints } = useMemo(() => {
    if (!spec)
      return {
        grouped: new Map<string, GroupedEndpoint[]>(),
        tags: [] as string[],
        methodCounts: {} as Record<string, number>,
        totalEndpoints: 0,
      };

    const map = new Map<string, GroupedEndpoint[]>();
    const mCounts: Record<string, number> = {};
    let total = 0;
    const searchLower = search.toLowerCase();

    for (const [path, methods] of Object.entries(spec.paths)) {
      for (const [method, operation] of Object.entries(methods)) {
        if (method.startsWith('x-') || method === 'parameters') continue;
        const methodUpper = method.toUpperCase();

        // Apply filters
        if (selectedMethod && methodUpper !== selectedMethod) continue;

        const opTags = operation.tags?.length ? operation.tags : ['Untagged'];

        if (selectedTag && !opTags.includes(selectedTag)) continue;

        if (searchLower) {
          const searchable =
            `${path} ${operation.summary || ''} ${operation.operationId || ''} ${operation.description || ''}`.toLowerCase();
          if (!searchable.includes(searchLower)) continue;
        }

        total++;
        mCounts[methodUpper] = (mCounts[methodUpper] || 0) + 1;

        for (const tag of opTags) {
          if (!map.has(tag)) map.set(tag, []);
          map.get(tag)!.push({ path, method: methodUpper, operation });
        }
      }
    }

    // Sort tags alphabetically
    const sortedTags = Array.from(map.keys()).sort();
    return { grouped: map, tags: sortedTags, methodCounts: mCounts, totalEndpoints: total };
  }, [spec, search, selectedTag, selectedMethod]);

  // Tag descriptions from spec
  const tagDescriptions = useMemo(() => {
    const desc: Record<string, string> = {};
    spec?.tags?.forEach((t) => {
      if (t.description) desc[t.name] = t.description;
    });
    return desc;
  }, [spec]);

  const togglePath = (key: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-3 mb-2">
              <Link
                href="/dashboard"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                DASHBOARD
              </Link>
              <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">API DOCS</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-1">
              {'>'} API REFERENCE
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data">
              {spec
                ? `OpenAPI ${spec.openapi} // ${spec.info.title} v${spec.info.version} // ${totalEndpoints} endpoints`
                : 'Loading API specification...'}
            </p>
          </div>

          {/* Loading / Error */}
          {loading && (
            <div className="card p-8 text-center">
              <div className="text-[var(--acid-green)] font-theme-data animate-pulse">
                Loading OpenAPI spec...
              </div>
            </div>
          )}

          {error && (
            <div className="card p-6 border-red-500/40">
              <p className="font-theme-data text-sm text-red-400 mb-2">Failed to load API spec</p>
              <p className="font-theme-data text-xs text-[var(--text-muted)]">{error}</p>
              <p className="font-theme-data text-xs text-[var(--text-muted)] mt-2">
                Ensure the backend is running at {API_BASE_URL}
              </p>
            </div>
          )}

          {spec && !loading && (
            <>
              {/* Filters */}
              <div className="flex flex-wrap items-center gap-3 mb-6">
                {/* Search */}
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search endpoints..."
                  className="flex-1 min-w-[200px] max-w-md px-3 py-2 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]/50"
                />

                {/* Method filter */}
                <div className="flex items-center gap-1">
                  {HTTP_METHODS.map((m) => (
                    <button
                      key={m}
                      onClick={() => setSelectedMethod(selectedMethod === m ? null : m)}
                      className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                        selectedMethod === m
                          ? METHOD_COLORS[m] || 'bg-[var(--surface)] text-[var(--text)]'
                          : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/30'
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>

                {/* Tag dropdown */}
                <select
                  value={selectedTag || ''}
                  onChange={(e) => setSelectedTag(e.target.value || null)}
                  className="px-2 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] focus:outline-none focus:border-[var(--acid-green)]/50"
                >
                  <option value="">All tags ({tags.length})</option>
                  {tags.map((t) => (
                    <option key={t} value={t}>
                      {t} ({grouped.get(t)?.length || 0})
                    </option>
                  ))}
                </select>

                {/* Stats */}
                <div className="text-xs font-theme-data text-[var(--text-muted)] ml-auto flex gap-3">
                  {Object.entries(methodCounts)
                    .sort()
                    .map(([m, c]) => (
                      <span key={m} className={METHOD_COLORS[m]?.split(' ')[1] || ''}>
                        {m}: {c}
                      </span>
                    ))}
                </div>
              </div>

              {/* Endpoint groups */}
              <div className="space-y-4">
                {tags.map((tag) => {
                  const endpoints = grouped.get(tag) || [];
                  return (
                    <section
                      key={tag}
                      className="border border-[var(--border)] bg-[var(--surface)]/50"
                    >
                      {/* Tag header */}
                      <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--surface)]">
                        <div className="flex items-center justify-between">
                          <h2 className="text-sm font-theme-data text-[var(--acid-green)] font-bold">
                            {tag}
                          </h2>
                          <span className="text-xs font-theme-data text-[var(--text-muted)]">
                            {endpoints.length} endpoint{endpoints.length !== 1 ? 's' : ''}
                          </span>
                        </div>
                        {tagDescriptions[tag] && (
                          <p className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                            {tagDescriptions[tag]}
                          </p>
                        )}
                      </div>

                      {/* Endpoints */}
                      <div className="divide-y divide-[var(--border)]/50">
                        {endpoints.map(({ path, method, operation }) => {
                          const key = `${method}-${path}`;
                          const isExpanded = expandedPaths.has(key);
                          return (
                            <div key={key}>
                              {/* Endpoint row */}
                              <button
                                onClick={() => togglePath(key)}
                                className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-[var(--acid-green)]/5 transition-colors text-left"
                              >
                                {/* Method badge */}
                                <span
                                  className={`inline-block w-16 text-center px-2 py-0.5 text-[10px] font-theme-data font-bold border ${
                                    METHOD_COLORS[method] ||
                                    'bg-gray-500/20 text-gray-400 border-gray-500/40'
                                  }`}
                                >
                                  {method}
                                </span>

                                {/* Path */}
                                <code className="text-xs font-theme-data text-[var(--text)] flex-1 truncate">
                                  {path}
                                </code>

                                {/* Badges */}
                                {operation.deprecated && (
                                  <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-yellow-500/20 text-yellow-400 border border-yellow-500/40">
                                    DEPRECATED
                                  </span>
                                )}

                                {/* Summary */}
                                {operation.summary && (
                                  <span className="text-xs font-theme-data text-[var(--text-muted)] max-w-xs truncate hidden md:inline">
                                    {operation.summary}
                                  </span>
                                )}

                                {/* Expand chevron */}
                                <span className="text-[var(--text-muted)] text-xs">
                                  {isExpanded ? '[-]' : '[+]'}
                                </span>
                              </button>

                              {/* Expanded details */}
                              {isExpanded && (
                                <EndpointDetails
                                  operation={operation}
                                  path={path}
                                  method={method}
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>

              {/* Empty state */}
              {tags.length === 0 && (
                <div className="card p-8 text-center">
                  <p className="font-theme-data text-sm text-[var(--text-muted)]">
                    No endpoints match your filters.
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // API REFERENCE</p>
        </footer>
      </main>
    </>
  );
}

// ---- Endpoint Details Sub-Component ----

function EndpointDetails({
  operation,
  path: _path,
  method: _method,
}: {
  operation: OpenAPIOperation;
  path: string;
  method: string;
}) {
  return (
    <div className="px-4 py-3 bg-[var(--bg)] border-t border-[var(--border)]/30 space-y-3">
      {/* Description */}
      {operation.description && (
        <div>
          <p className="text-xs font-theme-data text-[var(--text-muted)]">
            {operation.description}
          </p>
        </div>
      )}

      {/* Operation ID */}
      {operation.operationId && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
            Operation ID:
          </span>
          <code className="text-xs font-theme-data text-[var(--acid-cyan)]">
            {operation.operationId}
          </code>
        </div>
      )}

      {/* Parameters */}
      {operation.parameters && operation.parameters.length > 0 && (
        <div>
          <h4 className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
            Parameters
          </h4>
          <div className="border border-[var(--border)]/50 divide-y divide-[var(--border)]/30">
            {operation.parameters.map((param, i) => (
              <div key={i} className="px-3 py-2 flex items-start gap-3 text-xs font-theme-data">
                <code className="text-[var(--acid-green)] min-w-[100px]">{param.name}</code>
                <span className="text-[var(--text-muted)] min-w-[50px]">{param.in}</span>
                <span className="text-[var(--text-muted)]">{param.schema?.type || 'string'}</span>
                {param.required && <span className="text-red-400 text-[10px]">required</span>}
                {param.description && (
                  <span className="text-[var(--text-muted)] ml-auto truncate max-w-xs">
                    {param.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Request Body */}
      {operation.requestBody && (
        <div>
          <h4 className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
            Request Body
            {operation.requestBody.required && <span className="text-red-400 ml-2">required</span>}
          </h4>
          {operation.requestBody.content && (
            <div className="border border-[var(--border)]/50">
              {Object.entries(operation.requestBody.content).map(([contentType, media]) => (
                <div key={contentType} className="px-3 py-2">
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {contentType}
                  </span>
                  {media.schema && (
                    <pre className="mt-1 text-[11px] font-theme-data text-[var(--text-muted)] overflow-x-auto max-h-40 overflow-y-auto">
                      {JSON.stringify(media.schema, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Responses */}
      {operation.responses && Object.keys(operation.responses).length > 0 && (
        <div>
          <h4 className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
            Responses
          </h4>
          <div className="border border-[var(--border)]/50 divide-y divide-[var(--border)]/30">
            {Object.entries(operation.responses).map(([status, response]) => (
              <div key={status} className="px-3 py-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs font-theme-data font-bold ${
                      status.startsWith('2')
                        ? 'text-emerald-400'
                        : status.startsWith('4')
                          ? 'text-amber-400'
                          : status.startsWith('5')
                            ? 'text-red-400'
                            : 'text-[var(--text-muted)]'
                    }`}
                  >
                    {status}
                  </span>
                  <span className="text-xs font-theme-data text-[var(--text-muted)]">
                    {response.description}
                  </span>
                </div>
                {response.content && (
                  <div className="mt-1">
                    {Object.entries(response.content).map(([ct, media]) =>
                      media.schema ? (
                        <pre
                          key={ct}
                          className="text-[11px] font-theme-data text-[var(--text-muted)] overflow-x-auto max-h-32 overflow-y-auto"
                        >
                          {JSON.stringify(media.schema, null, 2)}
                        </pre>
                      ) : null,
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
