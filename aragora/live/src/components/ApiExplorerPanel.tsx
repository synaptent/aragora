'use client';

import { useState, useMemo } from 'react';
import { CollapsibleSection } from '@/components/CollapsibleSection';
import { ExperimentalBadge } from '@/components/shared/ExperimentalBadge';
import { type FeatureStatus } from '@/lib/featureFlags';
import {
  useApiExplorer,
  type HttpMethod,
  type OpenApiSchema,
  type OpenApiResponse,
  type OpenApiStability,
} from '@/hooks/useApiExplorer';

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------

const METHOD_COLORS: Record<string, string> = {
  GET: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
  POST: 'text-[var(--accent)] bg-[var(--accent)]/10 border-[var(--accent)]/30',
  PUT: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  DELETE: 'text-red-400 bg-red-400/10 border-red-400/30',
  PATCH: 'text-purple-400 bg-purple-400/10 border-purple-400/30',
  HEAD: 'text-text-muted bg-text-muted/10 border-text-muted/30',
  OPTIONS: 'text-text-muted bg-text-muted/10 border-text-muted/30',
};

const STATUS_COLORS: Record<string, string> = {
  '2': 'text-[var(--accent)]',
  '3': 'text-[var(--acid-cyan)]',
  '4': 'text-yellow-400',
  '5': 'text-red-400',
};

function getStatusColor(status: number): string {
  const key = String(status).charAt(0);
  return STATUS_COLORS[key] || 'text-text-muted';
}

const METHOD_LIST: HttpMethod[] = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'];

function getBadgeStatus(
  stability: OpenApiStability | undefined,
  deprecated: boolean | undefined,
): FeatureStatus | null {
  if (deprecated || stability === 'deprecated') {
    return 'deprecated';
  }
  if (stability === 'beta') {
    return 'beta';
  }
  if (stability === 'experimental' || stability === 'internal') {
    return 'alpha';
  }
  return null;
}

// ---------------------------------------------------------------------------
// SchemaViewer -- renders OpenAPI schema as a readable tree
// ---------------------------------------------------------------------------

function SchemaViewer({
  schema,
  resolveRef,
  getTypeString,
  depth = 0,
}: {
  schema: OpenApiSchema | undefined;
  resolveRef: (s: OpenApiSchema | undefined) => OpenApiSchema | undefined;
  getTypeString: (s: OpenApiSchema | undefined) => string;
  depth?: number;
}) {
  if (!schema || depth > 4) return null;

  const resolved = resolveRef(schema) || schema;

  if (resolved.type === 'object' && resolved.properties) {
    return (
      <div className="space-y-1">
        {Object.entries(resolved.properties).map(([key, propSchema]) => {
          const isRequired = resolved.required?.includes(key);
          const prop = resolveRef(propSchema) || propSchema;
          return (
            <div key={key} style={{ paddingLeft: depth * 16 }}>
              <div className="flex items-baseline gap-2">
                <span className="text-[var(--acid-cyan)] font-theme-data text-xs">{key}</span>
                {isRequired && <span className="text-red-400 text-[10px]">*</span>}
                <span className="text-text-muted font-theme-data text-[10px]">
                  {getTypeString(propSchema)}
                </span>
              </div>
              {prop.description && (
                <p
                  className="text-[10px] text-text-muted/70 font-theme-data"
                  style={{ paddingLeft: 8 }}
                >
                  {prop.description}
                </p>
              )}
              {prop.type === 'object' && prop.properties && (
                <SchemaViewer
                  schema={prop}
                  resolveRef={resolveRef}
                  getTypeString={getTypeString}
                  depth={depth + 1}
                />
              )}
            </div>
          );
        })}
      </div>
    );
  }

  if (resolved.type === 'array' && resolved.items) {
    return (
      <div style={{ paddingLeft: depth * 16 }}>
        <span className="text-text-muted font-theme-data text-[10px]">
          items: {getTypeString(resolved.items)}
        </span>
        {(resolveRef(resolved.items) || resolved.items)?.type === 'object' && (
          <SchemaViewer
            schema={resolved.items}
            resolveRef={resolveRef}
            getTypeString={getTypeString}
            depth={depth + 1}
          />
        )}
      </div>
    );
  }

  return (
    <div style={{ paddingLeft: depth * 16 }}>
      <span className="text-text-muted font-theme-data text-[10px]">{getTypeString(resolved)}</span>
      {resolved.description && (
        <p className="text-[10px] text-text-muted/70 font-theme-data">{resolved.description}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ResponseSchemaSection -- shows response schemas for an endpoint
// ---------------------------------------------------------------------------

function ResponseSchemaSection({
  responses,
  resolveRef,
  getTypeString,
}: {
  responses: Record<string, OpenApiResponse>;
  resolveRef: (s: OpenApiSchema | undefined) => OpenApiSchema | undefined;
  getTypeString: (s: OpenApiSchema | undefined) => string;
}) {
  const entries = Object.entries(responses);
  if (entries.length === 0) return null;

  return (
    <div className="space-y-3">
      {entries.map(([code, resp]) => {
        const schema = resp.content?.['application/json']?.schema;
        return (
          <div key={code} className="border border-[var(--accent)]/15 bg-black/20 p-3">
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`font-theme-data text-xs font-bold ${getStatusColor(parseInt(code, 10) || 0)}`}
              >
                {code}
              </span>
              <span className="text-xs font-theme-data text-text-muted">{resp.description}</span>
            </div>
            {schema && (
              <div className="pl-2 border-l border-[var(--accent)]/20">
                <SchemaViewer
                  schema={schema}
                  resolveRef={resolveRef}
                  getTypeString={getTypeString}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RequestHistoryBar -- compact history display
// ---------------------------------------------------------------------------

function RequestHistoryBar({
  history,
  onClear,
}: {
  history: Array<{
    id: string;
    timestamp: number;
    method: HttpMethod;
    url: string;
    status: number;
    statusText: string;
    elapsed: number;
  }>;
  onClear: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  if (history.length === 0) return null;

  return (
    <div className="border border-[var(--accent)]/20 bg-surface/30">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-theme-data text-text-muted hover:text-text transition-colors"
      >
        <span>
          [{expanded ? '-' : '+'}] REQUEST HISTORY ({history.length})
        </span>
        {expanded && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
            className="text-red-400/70 hover:text-red-400 text-[10px]"
          >
            CLEAR
          </button>
        )}
      </button>
      {expanded && (
        <div className="px-3 pb-2 max-h-48 overflow-y-auto space-y-1">
          {history.map((entry) => (
            <div key={entry.id} className="flex items-center gap-2 text-[10px] font-theme-data">
              <span className={`px-1 border ${METHOD_COLORS[entry.method]} shrink-0`}>
                {entry.method}
              </span>
              <span className={`font-bold ${getStatusColor(entry.status)}`}>{entry.status}</span>
              <span className="text-text truncate flex-1">{entry.url}</span>
              <span className="text-text-muted shrink-0">{entry.elapsed}ms</span>
              <span className="text-text-muted shrink-0">
                {new Date(entry.timestamp).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ApiExplorerPanel -- main exported component
// ---------------------------------------------------------------------------

export function ApiExplorerPanel() {
  const explorer = useApiExplorer();
  const [showHeaders, setShowHeaders] = useState(false);
  const [showResponseHeaders, setShowResponseHeaders] = useState(false);
  const [activeTab, setActiveTab] = useState<'try-it' | 'schema'>('try-it');

  // Auth token display
  const authToken = useMemo(() => {
    if (typeof window === 'undefined') return null;
    const stored = localStorage.getItem('aragora_tokens');
    if (!stored) return null;
    try {
      return (JSON.parse(stored) as { access_token?: string }).access_token || null;
    } catch {
      return null;
    }
  }, []);

  // Loading state
  if (explorer.specLoading) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/30 p-8 text-center">
        <div className="text-[var(--accent)] font-theme-data text-sm animate-pulse">
          Loading OpenAPI specification...
        </div>
        <p className="text-xs text-text-muted font-theme-data mt-2">
          Fetching from /api/openapi.json
        </p>
      </div>
    );
  }

  // Error state with fallback note
  if (explorer.specError && !explorer.spec) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/30 p-8 text-center space-y-4">
        <div className="text-yellow-400 font-theme-data text-sm">
          Could not load live OpenAPI spec
        </div>
        <p className="text-xs text-text-muted font-theme-data">{explorer.specError}</p>
        <button
          onClick={explorer.reloadSpec}
          className="px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-xs hover:bg-[var(--accent)]/10 transition-colors"
        >
          RETRY
        </button>
      </div>
    );
  }

  const ep = explorer.selectedEndpoint;
  const selectedBadgeStatus = ep ? getBadgeStatus(ep.stability, ep.deprecated) : null;

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="flex items-center gap-4 flex-wrap text-xs font-theme-data text-text-muted">
        <span>
          {explorer.spec?.info.title || 'Aragora API'} v{explorer.spec?.info.version || '?'}
        </span>
        <span>|</span>
        <span>{explorer.totalCount} endpoints</span>
        <span>|</span>
        <span>{explorer.allTags.length} tags</span>
        {explorer.spec?.openapi && (
          <>
            <span>|</span>
            <span>OpenAPI {explorer.spec.openapi}</span>
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* ---- Left Sidebar: Filters + Endpoint Tree ---- */}
        <div className="lg:col-span-4 space-y-4">
          {/* Search + Filters */}
          <div className="border border-[var(--accent)]/30 bg-surface/30 p-3 space-y-3">
            {/* Search box */}
            <div className="relative">
              <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--accent)]/50 font-theme-data text-sm">
                /
              </span>
              <input
                type="text"
                value={explorer.searchQuery}
                onChange={(e) => explorer.setSearchQuery(e.target.value)}
                placeholder="Search endpoints..."
                className="w-full bg-black/30 border border-[var(--accent)]/30 pl-6 pr-3 py-2 text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
              />
            </div>

            {/* Method filter pills */}
            <div className="flex flex-wrap gap-1">
              <button
                onClick={() => explorer.setMethodFilter(null)}
                className={`px-2 py-0.5 text-[10px] font-theme-data border transition-colors ${
                  !explorer.methodFilter
                    ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'border-[var(--accent)]/20 text-text-muted hover:text-text'
                }`}
              >
                ALL
              </button>
              {METHOD_LIST.map((m) => (
                <button
                  key={m}
                  onClick={() => explorer.setMethodFilter(explorer.methodFilter === m ? null : m)}
                  className={`px-2 py-0.5 text-[10px] font-theme-data border transition-colors ${
                    explorer.methodFilter === m
                      ? METHOD_COLORS[m]
                      : 'border-[var(--accent)]/20 text-text-muted hover:text-text'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>

            {/* Tag filter dropdown */}
            <select
              value={explorer.tagFilter || ''}
              onChange={(e) => explorer.setTagFilter(e.target.value || null)}
              className="w-full bg-black/30 border border-[var(--accent)]/30 px-2 py-1.5 text-xs font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
            >
              <option value="">All tags ({explorer.allTags.length})</option>
              {explorer.allTags.map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </select>

            {/* Count */}
            <p className="text-xs font-theme-data text-text-muted">
              {explorer.searchQuery || explorer.methodFilter || explorer.tagFilter
                ? `${explorer.filteredCount} of ${explorer.totalCount}`
                : `${explorer.totalCount}`}{' '}
              endpoints
            </p>
          </div>

          {/* Endpoint tree */}
          <div className="border border-[var(--accent)]/30 bg-surface/30 p-3 space-y-1 max-h-[calc(100vh-24rem)] overflow-y-auto">
            {explorer.filteredGroups.map((group) => (
              <CollapsibleSection
                key={group.tag}
                id={`api-cat-${group.tag.toLowerCase().replace(/\s+/g, '-')}`}
                title={`${group.tag} (${group.endpoints.length})`}
                defaultOpen={
                  (ep && ep.tag === group.tag) || !!(explorer.searchQuery || explorer.tagFilter)
                }
              >
                <div className="space-y-0.5">
                  {group.endpoints.map((endpoint) => {
                    const isSelected = ep?.path === endpoint.path && ep?.method === endpoint.method;
                    const badgeStatus = getBadgeStatus(endpoint.stability, endpoint.deprecated);
                    return (
                      <button
                        key={`${endpoint.method}-${endpoint.path}`}
                        onClick={() => explorer.selectEndpoint(endpoint)}
                        className={`w-full text-left px-2 py-1.5 transition-colors ${
                          isSelected
                            ? 'bg-[var(--accent)]/15 border-l-2 border-[var(--accent)]'
                            : 'hover:bg-[var(--accent)]/5 border-l-2 border-transparent'
                        } ${endpoint.deprecated ? 'opacity-50' : ''}`}
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-[10px] font-theme-data font-bold px-1 py-0.5 border ${
                              METHOD_COLORS[endpoint.method] ||
                              'border-text-muted/30 text-text-muted'
                            } shrink-0 w-12 text-center`}
                          >
                            {endpoint.method}
                          </span>
                          <span className="text-xs font-theme-data text-text truncate">
                            {endpoint.path}
                          </span>
                          {badgeStatus && <ExperimentalBadge status={badgeStatus} size="sm" />}
                          {endpoint.deprecated && (
                            <span className="text-[9px] font-theme-data text-yellow-400 border border-yellow-400/30 px-1">
                              DEP
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-text-muted mt-0.5 truncate pl-14">
                          {endpoint.summary}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </CollapsibleSection>
            ))}

            {explorer.filteredGroups.length === 0 && (
              <div className="text-center py-8">
                <p className="text-text-muted font-theme-data text-sm">
                  No endpoints match your filters
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ---- Main Panel: Endpoint Detail + Try It ---- */}
        <div className="lg:col-span-8 space-y-4">
          {ep ? (
            <>
              {/* Endpoint header */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-5">
                <div className="flex items-center gap-3 mb-2 flex-wrap">
                  <span
                    className={`text-sm font-theme-data font-bold px-2 py-1 border ${
                      METHOD_COLORS[ep.method] || ''
                    }`}
                  >
                    {ep.method}
                  </span>
                  <code className="text-base font-theme-data text-[var(--acid-cyan)] break-all">
                    {ep.path}
                  </code>
                  {selectedBadgeStatus && (
                    <ExperimentalBadge status={selectedBadgeStatus} size="sm" />
                  )}
                  {ep.deprecated && (
                    <span className="text-xs font-theme-data text-yellow-400 border border-yellow-400/30 px-1.5 py-0.5">
                      DEPRECATED
                    </span>
                  )}
                </div>
                <h2 className="text-lg font-theme-data text-[var(--accent)]">{ep.summary}</h2>
                {ep.description && (
                  <p className="text-sm text-text-muted mt-1 font-theme-data">{ep.description}</p>
                )}
                <div className="flex gap-4 mt-2 text-xs font-theme-data flex-wrap">
                  {ep.requiresAuth && (
                    <span className="text-yellow-400 border border-yellow-400/30 px-1.5 py-0.5">
                      AUTH REQUIRED
                    </span>
                  )}
                  {ep.operation.operationId && (
                    <span className="text-text-muted border border-text-muted/30 px-1.5 py-0.5">
                      {ep.operation.operationId}
                    </span>
                  )}
                  <span className="text-text-muted border border-text-muted/30 px-1.5 py-0.5">
                    {ep.tag}
                  </span>
                </div>
              </div>

              {/* Tabs */}
              <div className="flex gap-0 border-b border-[var(--accent)]/30">
                <button
                  onClick={() => setActiveTab('try-it')}
                  className={`px-4 py-2 text-xs font-theme-data border-b-2 transition-colors ${
                    activeTab === 'try-it'
                      ? 'border-[var(--accent)] text-[var(--accent)]'
                      : 'border-transparent text-text-muted hover:text-text'
                  }`}
                >
                  TRY IT
                </button>
                <button
                  onClick={() => setActiveTab('schema')}
                  className={`px-4 py-2 text-xs font-theme-data border-b-2 transition-colors ${
                    activeTab === 'schema'
                      ? 'border-[var(--accent)] text-[var(--accent)]'
                      : 'border-transparent text-text-muted hover:text-text'
                  }`}
                >
                  SCHEMA
                </button>
              </div>

              {/* Tab content */}
              {activeTab === 'try-it' && (
                <div className="border border-[var(--accent)]/30 bg-surface/30 p-5 space-y-5">
                  {/* Base URL */}
                  <div className="space-y-1">
                    <label className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
                      Base URL
                    </label>
                    <input
                      type="text"
                      value={explorer.baseUrl}
                      onChange={(e) => explorer.setBaseUrl(e.target.value)}
                      className="w-full bg-black/30 border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>

                  {/* Path Parameters */}
                  {ep.pathParams.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
                        Path Parameters
                      </h4>
                      {ep.pathParams.map((param) => (
                        <div key={param.name} className="flex items-center gap-2">
                          <label className="text-sm font-theme-data w-32 text-[var(--acid-cyan)] shrink-0">
                            {param.name}
                            {param.required && <span className="text-red-400">*</span>}:
                          </label>
                          <input
                            type="text"
                            value={explorer.pathValues[param.name] || ''}
                            onChange={(e) => explorer.setPathValue(param.name, e.target.value)}
                            placeholder={param.description || param.schema?.type || 'string'}
                            className="flex-1 bg-black/30 border border-[var(--accent)]/30 px-2 py-1.5 text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Query Parameters */}
                  {ep.queryParams.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
                        Query Parameters
                      </h4>
                      {ep.queryParams.map((param) => (
                        <div key={param.name} className="flex items-center gap-2">
                          <label className="text-sm font-theme-data w-32 text-[var(--acid-cyan)] shrink-0">
                            {param.name}
                            {param.required && <span className="text-red-400">*</span>}:
                          </label>
                          <input
                            type="text"
                            value={explorer.queryValues[param.name] || ''}
                            onChange={(e) => explorer.setQueryValue(param.name, e.target.value)}
                            placeholder={param.description || param.schema?.type || 'string'}
                            className="flex-1 bg-black/30 border border-[var(--accent)]/30 px-2 py-1.5 text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                          />
                          {param.schema?.enum && (
                            <span className="text-[10px] font-theme-data text-text-muted shrink-0">
                              [{param.schema.enum.slice(0, 4).join(', ')}
                              {param.schema.enum.length > 4 ? '...' : ''}]
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Request Body */}
                  {ep.method !== 'GET' && ep.method !== 'HEAD' && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
                        Request Body
                        {ep.requestBody?.required && <span className="text-red-400 ml-1">*</span>}
                      </h4>
                      <textarea
                        value={explorer.bodyValue}
                        onChange={(e) => explorer.setBodyValue(e.target.value)}
                        rows={10}
                        className="w-full bg-black/30 border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-[var(--accent)] focus:border-[var(--accent)] focus:outline-none resize-y"
                        placeholder="JSON request body"
                        spellCheck={false}
                      />
                    </div>
                  )}

                  {/* Headers */}
                  <div className="space-y-2">
                    <button
                      type="button"
                      onClick={() => setShowHeaders(!showHeaders)}
                      className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                    >
                      [{showHeaders ? '-' : '+'}] HEADERS
                      {authToken && (
                        <span className="text-[var(--accent)]/60 ml-2">(auth token detected)</span>
                      )}
                    </button>

                    {showHeaders && (
                      <div className="space-y-2 border border-[var(--accent)]/20 p-3 bg-black/20">
                        {authToken && (
                          <div className="flex items-center gap-2 opacity-60">
                            <span className="text-xs font-theme-data w-28 text-[var(--accent)] shrink-0">
                              Authorization:
                            </span>
                            <span className="text-xs font-theme-data text-text truncate">
                              Bearer {authToken.slice(0, 20)}...
                            </span>
                            <span className="text-xs font-theme-data text-[var(--accent)]/50 ml-auto">
                              (auto)
                            </span>
                          </div>
                        )}
                        <div className="flex items-center gap-2 opacity-60">
                          <span className="text-xs font-theme-data w-28 text-[var(--accent)] shrink-0">
                            Content-Type:
                          </span>
                          <span className="text-xs font-theme-data text-text">
                            application/json
                          </span>
                          <span className="text-xs font-theme-data text-[var(--accent)]/50 ml-auto">
                            (auto)
                          </span>
                        </div>

                        {explorer.customHeaders.map((h, idx) => (
                          <div key={idx} className="flex items-center gap-2">
                            <input
                              type="text"
                              value={h.key}
                              onChange={(e) => explorer.updateHeader(idx, 'key', e.target.value)}
                              placeholder="Header name"
                              className="w-28 bg-black/30 border border-[var(--accent)]/30 px-2 py-1 text-xs font-theme-data text-text focus:border-[var(--accent)] focus:outline-none shrink-0"
                            />
                            <input
                              type="text"
                              value={h.value}
                              onChange={(e) => explorer.updateHeader(idx, 'value', e.target.value)}
                              placeholder="Value"
                              className="flex-1 bg-black/30 border border-[var(--accent)]/30 px-2 py-1 text-xs font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={() => explorer.removeHeader(idx)}
                              className="text-red-400 hover:text-red-300 text-xs font-theme-data px-1"
                            >
                              x
                            </button>
                          </div>
                        ))}

                        <button
                          type="button"
                          onClick={explorer.addHeader}
                          className="text-xs font-theme-data text-[var(--accent)]/70 hover:text-[var(--accent)] transition-colors"
                        >
                          + Add Header
                        </button>
                      </div>
                    )}
                  </div>

                  {/* URL Preview */}
                  <div className="p-2 bg-black/30 border border-[var(--accent)]/20">
                    <span className="text-xs font-theme-data text-text-muted">URL: </span>
                    <code className="text-xs font-theme-data text-[var(--acid-cyan)] break-all">
                      {explorer.builtUrl}
                    </code>
                  </div>

                  {/* Send button */}
                  <button
                    type="button"
                    onClick={explorer.sendRequest}
                    disabled={explorer.requestLoading}
                    className="px-6 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                  >
                    {explorer.requestLoading ? 'SENDING...' : `TRY IT - ${ep.method}`}
                  </button>

                  {/* Error */}
                  {explorer.requestError && (
                    <div className="p-3 bg-red-500/10 border border-red-500/30">
                      <span className="text-sm font-theme-data text-red-400">
                        {explorer.requestError}
                      </span>
                    </div>
                  )}

                  {/* Response */}
                  {explorer.response && (
                    <div className="space-y-3 border-t border-[var(--accent)]/20 pt-4">
                      {/* Status line */}
                      <div className="flex items-center gap-4 font-theme-data text-sm">
                        <span className="text-text-muted">Status:</span>
                        <span className={`font-bold ${getStatusColor(explorer.response.status)}`}>
                          {explorer.response.status} {explorer.response.statusText}
                        </span>
                        <span className="text-text-muted text-xs ml-auto">
                          {explorer.response.elapsed}ms
                        </span>
                      </div>

                      {/* Response headers toggle */}
                      <button
                        type="button"
                        onClick={() => setShowResponseHeaders(!showResponseHeaders)}
                        className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                      >
                        [{showResponseHeaders ? '-' : '+'}] RESPONSE HEADERS (
                        {Object.keys(explorer.response.headers).length})
                      </button>

                      {showResponseHeaders && (
                        <div className="bg-black/30 border border-[var(--accent)]/20 p-3 max-h-40 overflow-y-auto">
                          {Object.entries(explorer.response.headers).map(([key, value]) => (
                            <div key={key} className="text-xs font-theme-data">
                              <span className="text-[var(--acid-cyan)]">{key}</span>
                              <span className="text-text-muted">: </span>
                              <span className="text-text">{value}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Response body */}
                      <div>
                        <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider mb-2">
                          Response Body
                        </h4>
                        <pre className="p-3 bg-black/30 border border-[var(--accent)]/20 overflow-x-auto text-xs font-theme-data text-[var(--accent)] max-h-96 overflow-y-auto whitespace-pre-wrap">
                          {typeof explorer.response.body === 'string'
                            ? explorer.response.body
                            : JSON.stringify(explorer.response.body, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'schema' && (
                <div className="border border-[var(--accent)]/30 bg-surface/30 p-5 space-y-5">
                  {/* Request schema */}
                  {ep.requestBody?.content?.['application/json']?.schema && (
                    <div>
                      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
                        REQUEST BODY SCHEMA
                      </h3>
                      <div className="bg-black/20 border border-[var(--accent)]/15 p-3">
                        <SchemaViewer
                          schema={ep.requestBody.content['application/json'].schema}
                          resolveRef={explorer.resolveSchemaRef}
                          getTypeString={explorer.getSchemaTypeString}
                        />
                      </div>
                    </div>
                  )}

                  {/* Parameters summary */}
                  {(ep.pathParams.length > 0 || ep.queryParams.length > 0) && (
                    <div>
                      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
                        PARAMETERS
                      </h3>
                      <div className="bg-black/20 border border-[var(--accent)]/15 overflow-hidden">
                        <table className="w-full text-xs font-theme-data">
                          <thead>
                            <tr className="border-b border-[var(--accent)]/20">
                              <th className="text-left px-3 py-2 text-text-muted">Name</th>
                              <th className="text-left px-3 py-2 text-text-muted">In</th>
                              <th className="text-left px-3 py-2 text-text-muted">Type</th>
                              <th className="text-left px-3 py-2 text-text-muted">Required</th>
                              <th className="text-left px-3 py-2 text-text-muted">Description</th>
                            </tr>
                          </thead>
                          <tbody>
                            {[...ep.pathParams, ...ep.queryParams].map((param) => (
                              <tr
                                key={`${param.in}-${param.name}`}
                                className="border-b border-[var(--accent)]/10"
                              >
                                <td className="px-3 py-1.5 text-[var(--acid-cyan)]">
                                  {param.name}
                                </td>
                                <td className="px-3 py-1.5 text-text-muted">{param.in}</td>
                                <td className="px-3 py-1.5 text-text">
                                  {param.schema?.type || 'string'}
                                </td>
                                <td className="px-3 py-1.5">
                                  {param.required ? (
                                    <span className="text-red-400">yes</span>
                                  ) : (
                                    <span className="text-text-muted">no</span>
                                  )}
                                </td>
                                <td className="px-3 py-1.5 text-text-muted">
                                  {param.description || '-'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Response schemas */}
                  {Object.keys(ep.responses).length > 0 && (
                    <div>
                      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
                        RESPONSES
                      </h3>
                      <ResponseSchemaSection
                        responses={ep.responses}
                        resolveRef={explorer.resolveSchemaRef}
                        getTypeString={explorer.getSchemaTypeString}
                      />
                    </div>
                  )}

                  {/* No schema info */}
                  {!ep.requestBody?.content?.['application/json']?.schema &&
                    ep.pathParams.length === 0 &&
                    ep.queryParams.length === 0 &&
                    Object.keys(ep.responses).length === 0 && (
                      <div className="text-center py-8">
                        <p className="text-text-muted font-theme-data text-sm">
                          No schema information available for this endpoint
                        </p>
                      </div>
                    )}
                </div>
              )}

              {/* Request history */}
              <RequestHistoryBar history={explorer.history} onClear={explorer.clearHistory} />
            </>
          ) : (
            <div className="border border-[var(--accent)]/30 bg-surface/30 flex items-center justify-center h-96">
              <div className="text-center space-y-3">
                <div className="text-4xl font-theme-data text-[var(--accent)]/30">{'{}'}</div>
                <p className="text-text-muted font-theme-data text-sm">
                  Select an endpoint to explore
                </p>
                <p className="text-xs text-text-muted/70 font-theme-data">
                  {explorer.totalCount > 0
                    ? `Browse ${explorer.totalCount} endpoints across ${explorer.allTags.length} categories`
                    : 'Loading endpoints from OpenAPI spec...'}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
