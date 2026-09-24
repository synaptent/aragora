'use client';

import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// OpenAPI Types (subset of OpenAPI 3.1 we care about)
// ---------------------------------------------------------------------------

export interface OpenApiParameter {
  name: string;
  in: 'path' | 'query' | 'header' | 'cookie';
  required?: boolean;
  description?: string;
  schema?: OpenApiSchema;
}

export interface OpenApiSchema {
  type?: string;
  format?: string;
  description?: string;
  properties?: Record<string, OpenApiSchema>;
  items?: OpenApiSchema;
  required?: string[];
  enum?: string[];
  example?: unknown;
  default?: unknown;
  oneOf?: OpenApiSchema[];
  anyOf?: OpenApiSchema[];
  allOf?: OpenApiSchema[];
  $ref?: string;
  additionalProperties?: boolean | OpenApiSchema;
}

export interface OpenApiRequestBody {
  description?: string;
  required?: boolean;
  content?: Record<string, { schema?: OpenApiSchema; example?: unknown }>;
}

export interface OpenApiResponse {
  description?: string;
  content?: Record<string, { schema?: OpenApiSchema; example?: unknown }>;
}

export type OpenApiStability = 'stable' | 'beta' | 'experimental' | 'internal' | 'deprecated';

export interface OpenApiOperation {
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: OpenApiParameter[];
  requestBody?: OpenApiRequestBody;
  responses?: Record<string, OpenApiResponse>;
  security?: Array<Record<string, string[]>>;
  deprecated?: boolean;
  'x-aragora-stability'?: OpenApiStability;
}

export interface OpenApiSpec {
  openapi: string;
  info: { title: string; version: string; description?: string };
  paths: Record<string, Record<string, OpenApiOperation>>;
  components?: {
    schemas?: Record<string, OpenApiSchema>;
    securitySchemes?: Record<string, unknown>;
  };
  tags?: Array<{ name: string; description?: string }>;
}

// ---------------------------------------------------------------------------
// Parsed Endpoint
// ---------------------------------------------------------------------------

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS';

export interface ParsedEndpoint {
  path: string;
  method: HttpMethod;
  operation: OpenApiOperation;
  tag: string;
  summary: string;
  description?: string;
  deprecated?: boolean;
  stability?: OpenApiStability;
  requiresAuth: boolean;
  pathParams: OpenApiParameter[];
  queryParams: OpenApiParameter[];
  headerParams: OpenApiParameter[];
  requestBody?: OpenApiRequestBody;
  responses: Record<string, OpenApiResponse>;
}

export interface EndpointGroup {
  tag: string;
  description?: string;
  endpoints: ParsedEndpoint[];
}

// ---------------------------------------------------------------------------
// Request/Response types
// ---------------------------------------------------------------------------

export interface RequestHistoryEntry {
  id: string;
  timestamp: number;
  method: HttpMethod;
  url: string;
  status: number;
  statusText: string;
  elapsed: number;
}

export interface ApiResponse {
  status: number;
  statusText: string;
  headers: Record<string, string>;
  body: unknown;
  elapsed: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const HTTP_METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];

function resolveRef(spec: OpenApiSpec, ref: string): OpenApiSchema | null {
  // e.g. "#/components/schemas/Debate"
  const parts = ref.replace('#/', '').split('/');
  let current: unknown = spec;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return null;
    }
  }
  return current as OpenApiSchema;
}

function resolveSchema(
  spec: OpenApiSpec,
  schema: OpenApiSchema | undefined,
): OpenApiSchema | undefined {
  if (!schema) return undefined;
  if (schema.$ref) {
    const resolved = resolveRef(spec, schema.$ref);
    return resolved ?? undefined;
  }
  return schema;
}

function parseEndpoints(spec: OpenApiSpec): ParsedEndpoint[] {
  const endpoints: ParsedEndpoint[] = [];

  for (const [path, methods] of Object.entries(spec.paths || {})) {
    for (const [method, operation] of Object.entries(methods)) {
      const upperMethod = method.toUpperCase() as HttpMethod;
      if (!HTTP_METHODS.includes(upperMethod)) continue;

      const op = operation as OpenApiOperation;
      const stability = op['x-aragora-stability'];
      const tag = op.tags?.[0] || 'Untagged';
      const params = op.parameters || [];

      endpoints.push({
        path,
        method: upperMethod,
        operation: op,
        tag,
        summary: op.summary || `${upperMethod} ${path}`,
        description: op.description,
        deprecated: op.deprecated || stability === 'deprecated',
        stability,
        requiresAuth: !!(op.security && op.security.length > 0),
        pathParams: params.filter((p) => p.in === 'path'),
        queryParams: params.filter((p) => p.in === 'query'),
        headerParams: params.filter((p) => p.in === 'header'),
        requestBody: op.requestBody,
        responses: op.responses || {},
      });
    }
  }

  // Sort by path, then method
  endpoints.sort((a, b) => {
    const pathCmp = a.path.localeCompare(b.path);
    if (pathCmp !== 0) return pathCmp;
    return HTTP_METHODS.indexOf(a.method) - HTTP_METHODS.indexOf(b.method);
  });

  return endpoints;
}

function groupEndpoints(endpoints: ParsedEndpoint[]): EndpointGroup[] {
  const groupMap = new Map<string, ParsedEndpoint[]>();

  for (const ep of endpoints) {
    const existing = groupMap.get(ep.tag) || [];
    existing.push(ep);
    groupMap.set(ep.tag, existing);
  }

  return Array.from(groupMap.entries())
    .map(([tag, eps]) => ({ tag, endpoints: eps }))
    .sort((a, b) => a.tag.localeCompare(b.tag));
}

function generateExampleBody(spec: OpenApiSpec, requestBody?: OpenApiRequestBody): string {
  if (!requestBody?.content) return '';

  const jsonContent = requestBody.content['application/json'];
  if (!jsonContent) return '';

  if (jsonContent.example) {
    return JSON.stringify(jsonContent.example, null, 2);
  }

  const schema = resolveSchema(spec, jsonContent.schema);
  if (!schema) return '';

  try {
    const example = buildExampleFromSchema(spec, schema);
    return JSON.stringify(example, null, 2);
  } catch {
    return '{}';
  }
}

function buildExampleFromSchema(spec: OpenApiSpec, schema: OpenApiSchema, depth = 0): unknown {
  if (depth > 5) return null;

  const resolved = resolveSchema(spec, schema);
  if (!resolved) return null;

  if (resolved.example !== undefined) return resolved.example;
  if (resolved.default !== undefined) return resolved.default;
  if (resolved.enum && resolved.enum.length > 0) return resolved.enum[0];

  switch (resolved.type) {
    case 'string':
      if (resolved.format === 'date-time') return '2026-01-01T00:00:00Z';
      if (resolved.format === 'date') return '2026-01-01';
      if (resolved.format === 'email') return 'user@example.com';
      if (resolved.format === 'uuid') return '00000000-0000-0000-0000-000000000000';
      return 'string';
    case 'integer':
    case 'number':
      return 0;
    case 'boolean':
      return true;
    case 'array':
      if (resolved.items) {
        return [buildExampleFromSchema(spec, resolved.items, depth + 1)];
      }
      return [];
    case 'object':
      if (resolved.properties) {
        const obj: Record<string, unknown> = {};
        for (const [key, propSchema] of Object.entries(resolved.properties)) {
          obj[key] = buildExampleFromSchema(spec, propSchema, depth + 1);
        }
        return obj;
      }
      return {};
    default:
      // Handle allOf / oneOf / anyOf
      if (resolved.allOf) {
        const merged: Record<string, unknown> = {};
        for (const sub of resolved.allOf) {
          const val = buildExampleFromSchema(spec, sub, depth + 1);
          if (val && typeof val === 'object') Object.assign(merged, val);
        }
        return merged;
      }
      if (resolved.oneOf?.[0]) return buildExampleFromSchema(spec, resolved.oneOf[0], depth + 1);
      if (resolved.anyOf?.[0]) return buildExampleFromSchema(spec, resolved.anyOf[0], depth + 1);
      return null;
  }
}

// ---------------------------------------------------------------------------
// Schema display helpers
// ---------------------------------------------------------------------------

export function schemaToTypeString(
  spec: OpenApiSpec,
  schema: OpenApiSchema | undefined,
  depth = 0,
): string {
  if (!schema) return 'unknown';
  if (depth > 4) return '...';

  const resolved = resolveSchema(spec, schema);
  if (!resolved) return schema.$ref?.split('/').pop() || 'unknown';

  if (resolved.enum) {
    return resolved.enum.map((v) => JSON.stringify(v)).join(' | ');
  }

  switch (resolved.type) {
    case 'array':
      return `Array<${schemaToTypeString(spec, resolved.items, depth + 1)}>`;
    case 'object': {
      if (!resolved.properties) return 'object';
      const props = Object.entries(resolved.properties)
        .slice(0, 8)
        .map(([k, v]) => {
          const optional = resolved.required?.includes(k) ? '' : '?';
          return `${k}${optional}: ${schemaToTypeString(spec, v, depth + 1)}`;
        });
      const more = Object.keys(resolved.properties).length > 8 ? ', ...' : '';
      return `{ ${props.join(', ')}${more} }`;
    }
    default:
      return resolved.type || 'unknown';
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseApiExplorerReturn {
  // Spec state
  spec: OpenApiSpec | null;
  specLoading: boolean;
  specError: string | null;
  reloadSpec: () => Promise<void>;

  // Parsed data
  allEndpoints: ParsedEndpoint[];
  groups: EndpointGroup[];
  filteredGroups: EndpointGroup[];
  filteredCount: number;
  totalCount: number;
  allTags: string[];

  // Filters
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  methodFilter: HttpMethod | null;
  setMethodFilter: (m: HttpMethod | null) => void;
  tagFilter: string | null;
  setTagFilter: (t: string | null) => void;

  // Selection
  selectedEndpoint: ParsedEndpoint | null;
  selectEndpoint: (ep: ParsedEndpoint | null) => void;

  // Request state
  baseUrl: string;
  setBaseUrl: (url: string) => void;
  pathValues: Record<string, string>;
  setPathValue: (name: string, value: string) => void;
  queryValues: Record<string, string>;
  setQueryValue: (name: string, value: string) => void;
  bodyValue: string;
  setBodyValue: (body: string) => void;
  customHeaders: Array<{ key: string; value: string }>;
  addHeader: () => void;
  removeHeader: (idx: number) => void;
  updateHeader: (idx: number, field: 'key' | 'value', val: string) => void;

  // Execution
  sendRequest: () => Promise<void>;
  requestLoading: boolean;
  requestError: string | null;
  response: ApiResponse | null;
  builtUrl: string;

  // History
  history: RequestHistoryEntry[];
  clearHistory: () => void;

  // Helpers
  getExampleBody: (ep: ParsedEndpoint) => string;
  resolveSchemaRef: (schema: OpenApiSchema | undefined) => OpenApiSchema | undefined;
  getSchemaTypeString: (schema: OpenApiSchema | undefined) => string;
}

const HISTORY_KEY = 'aragora_api_explorer_history';
const MAX_HISTORY = 50;

export function useApiExplorer(): UseApiExplorerReturn {
  // Spec state
  const [spec, setSpec] = useState<OpenApiSpec | null>(null);
  const [specLoading, setSpecLoading] = useState(true);
  const [specError, setSpecError] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [methodFilter, setMethodFilter] = useState<HttpMethod | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  // Selection
  const [selectedEndpoint, setSelectedEndpoint] = useState<ParsedEndpoint | null>(null);

  // Request builder state
  const [baseUrl, setBaseUrl] = useState(
    typeof window !== 'undefined' ? window.location.origin : API_BASE_URL,
  );
  const [pathValues, setPathValues] = useState<Record<string, string>>({});
  const [queryValues, setQueryValues] = useState<Record<string, string>>({});
  const [bodyValue, setBodyValue] = useState('');
  const [customHeaders, setCustomHeaders] = useState<Array<{ key: string; value: string }>>([]);

  // Response state
  const [requestLoading, setRequestLoading] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [response, setResponse] = useState<ApiResponse | null>(null);

  // History
  const [history, setHistory] = useState<RequestHistoryEntry[]>(() => {
    if (typeof window === 'undefined') return [];
    try {
      const stored = localStorage.getItem(HISTORY_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  // Abort controller for in-flight requests
  const abortRef = useRef<AbortController | null>(null);

  // Auth token
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

  // ---------------------------------------------------------------------------
  // Load OpenAPI spec
  // ---------------------------------------------------------------------------

  const loadSpec = useCallback(async () => {
    setSpecLoading(true);
    setSpecError(null);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);

      const res = await fetch(`${API_BASE_URL}/api/openapi.json`, { signal: controller.signal });
      clearTimeout(timeoutId);

      if (!res.ok) {
        throw new Error(`Failed to load OpenAPI spec: HTTP ${res.status}`);
      }

      const data = await res.json();
      setSpec(data as OpenApiSpec);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load API spec';
      setSpecError(msg);
    } finally {
      setSpecLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSpec();
  }, [loadSpec]);

  // ---------------------------------------------------------------------------
  // Parsed endpoints
  // ---------------------------------------------------------------------------

  const allEndpoints = useMemo(() => {
    if (!spec) return [];
    return parseEndpoints(spec);
  }, [spec]);

  const groups = useMemo(() => groupEndpoints(allEndpoints), [allEndpoints]);

  const allTags = useMemo(() => groups.map((g) => g.tag), [groups]);

  // ---------------------------------------------------------------------------
  // Filtering
  // ---------------------------------------------------------------------------

  const filteredGroups = useMemo(() => {
    let filtered = allEndpoints;
    const query = searchQuery.toLowerCase().trim();

    if (query) {
      filtered = filtered.filter(
        (ep) =>
          ep.path.toLowerCase().includes(query) ||
          ep.summary.toLowerCase().includes(query) ||
          ep.method.toLowerCase().includes(query) ||
          ep.tag.toLowerCase().includes(query) ||
          (ep.description || '').toLowerCase().includes(query) ||
          (ep.operation.operationId || '').toLowerCase().includes(query),
      );
    }

    if (methodFilter) {
      filtered = filtered.filter((ep) => ep.method === methodFilter);
    }

    if (tagFilter) {
      filtered = filtered.filter((ep) => ep.tag === tagFilter);
    }

    return groupEndpoints(filtered);
  }, [allEndpoints, searchQuery, methodFilter, tagFilter]);

  const filteredCount = useMemo(
    () => filteredGroups.reduce((sum, g) => sum + g.endpoints.length, 0),
    [filteredGroups],
  );

  const totalCount = allEndpoints.length;

  // ---------------------------------------------------------------------------
  // Selection
  // ---------------------------------------------------------------------------

  const selectEndpoint = useCallback(
    (ep: ParsedEndpoint | null) => {
      setSelectedEndpoint(ep);
      setResponse(null);
      setRequestError(null);

      if (ep && spec) {
        // Reset form values
        setPathValues({});
        setQueryValues({});
        setBodyValue(generateExampleBody(spec, ep.requestBody));
      }
    },
    [spec],
  );

  // ---------------------------------------------------------------------------
  // Request builder helpers
  // ---------------------------------------------------------------------------

  const setPathValue = useCallback((name: string, value: string) => {
    setPathValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  const setQueryValue = useCallback((name: string, value: string) => {
    setQueryValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  const addHeader = useCallback(() => {
    setCustomHeaders((prev) => [...prev, { key: '', value: '' }]);
  }, []);

  const removeHeader = useCallback((idx: number) => {
    setCustomHeaders((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const updateHeader = useCallback((idx: number, field: 'key' | 'value', val: string) => {
    setCustomHeaders((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      return next;
    });
  }, []);

  // ---------------------------------------------------------------------------
  // Build URL
  // ---------------------------------------------------------------------------

  const builtUrl = useMemo(() => {
    if (!selectedEndpoint) return '';

    let url = `${baseUrl}${selectedEndpoint.path}`;

    for (const [key, value] of Object.entries(pathValues)) {
      url = url.replace(`{${key}}`, encodeURIComponent(value || `{${key}}`));
    }

    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(queryValues)) {
      if (value) params.append(key, value);
    }
    const queryString = params.toString();
    if (queryString) url += `?${queryString}`;

    return url;
  }, [baseUrl, selectedEndpoint, pathValues, queryValues]);

  // ---------------------------------------------------------------------------
  // Send request
  // ---------------------------------------------------------------------------

  const sendRequest = useCallback(async () => {
    if (!selectedEndpoint) return;

    // Abort any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setRequestLoading(true);
    setRequestError(null);
    setResponse(null);

    const start = performance.now();

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };

      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      for (const h of customHeaders) {
        if (h.key.trim()) {
          headers[h.key.trim()] = h.value;
        }
      }

      const options: RequestInit = {
        method: selectedEndpoint.method,
        headers,
        signal: controller.signal,
      };

      if (selectedEndpoint.method !== 'GET' && selectedEndpoint.method !== 'HEAD' && bodyValue) {
        options.body = bodyValue;
      }

      const res = await fetch(builtUrl, options);
      const elapsed = Math.round(performance.now() - start);
      const body = await res.json().catch(() => res.text());

      const resHeaders: Record<string, string> = {};
      res.headers.forEach((value, key) => {
        resHeaders[key] = value;
      });

      const apiResponse: ApiResponse = {
        status: res.status,
        statusText: res.statusText,
        headers: resHeaders,
        body,
        elapsed,
      };

      setResponse(apiResponse);

      // Add to history
      const entry: RequestHistoryEntry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: Date.now(),
        method: selectedEndpoint.method,
        url: builtUrl,
        status: res.status,
        statusText: res.statusText,
        elapsed,
      };

      setHistory((prev) => {
        const next = [entry, ...prev].slice(0, MAX_HISTORY);
        try {
          localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
        } catch {
          // localStorage full, ignore
        }
        return next;
      });
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setRequestError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setRequestLoading(false);
    }
  }, [selectedEndpoint, builtUrl, bodyValue, customHeaders, authToken]);

  // ---------------------------------------------------------------------------
  // History
  // ---------------------------------------------------------------------------

  const clearHistory = useCallback(() => {
    setHistory([]);
    try {
      localStorage.removeItem(HISTORY_KEY);
    } catch {
      // ignore
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  const getExampleBody = useCallback(
    (ep: ParsedEndpoint): string => {
      if (!spec) return '';
      return generateExampleBody(spec, ep.requestBody);
    },
    [spec],
  );

  const resolveSchemaRef = useCallback(
    (schema: OpenApiSchema | undefined): OpenApiSchema | undefined => {
      if (!spec || !schema) return undefined;
      return resolveSchema(spec, schema);
    },
    [spec],
  );

  const getSchemaTypeString = useCallback(
    (schema: OpenApiSchema | undefined): string => {
      if (!spec) return 'unknown';
      return schemaToTypeString(spec, schema);
    },
    [spec],
  );

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return {
    spec,
    specLoading,
    specError,
    reloadSpec: loadSpec,

    allEndpoints,
    groups,
    filteredGroups,
    filteredCount,
    totalCount,
    allTags,

    searchQuery,
    setSearchQuery,
    methodFilter,
    setMethodFilter,
    tagFilter,
    setTagFilter,

    selectedEndpoint,
    selectEndpoint,

    baseUrl,
    setBaseUrl,
    pathValues,
    setPathValue,
    queryValues,
    setQueryValue,
    bodyValue,
    setBodyValue,
    customHeaders,
    addHeader,
    removeHeader,
    updateHeader,

    sendRequest,
    requestLoading,
    requestError,
    response,
    builtUrl,

    history,
    clearHistory,

    getExampleBody,
    resolveSchemaRef,
    getSchemaTypeString,
  };
}
