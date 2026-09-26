/**
 * Interactive API Playground
 *
 * Allows users to test API endpoints directly in the browser
 * with live request/response visualization.
 */

import React, { useState, useCallback } from 'react';

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  path: string;
  description: string;
  parameters?: Parameter[];
  body?: object;
}

interface Parameter {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object';
  required: boolean;
  description: string;
  default?: unknown;
}

interface RequestState {
  loading: boolean;
  response: unknown;
  error: string | null;
  duration: number | null;
  status: number | null;
}

// Predefined endpoints for the playground
const ENDPOINTS: Endpoint[] = [
  {
    method: 'POST',
    path: '/api/debates',
    description: 'Create a new debate',
    body: {
      task: 'What is the best programming paradigm?',
      agents: ['claude', 'gpt-4'],
      protocol: { rounds: 2, consensus: 'majority' },
    },
  },
  {
    method: 'GET',
    path: '/api/debates',
    description: 'List all debates',
    parameters: [
      { name: 'limit', type: 'number', required: false, description: 'Max results', default: 10 },
      {
        name: 'offset',
        type: 'number',
        required: false,
        description: 'Pagination offset',
        default: 0,
      },
    ],
  },
  {
    method: 'GET',
    path: '/api/debates/{debate_id}',
    description: 'Get debate details',
    parameters: [{ name: 'debate_id', type: 'string', required: true, description: 'Debate ID' }],
  },
  { method: 'GET', path: '/api/agents', description: 'List available agents' },
  {
    method: 'POST',
    path: '/api/agents/recommend',
    description: 'Get agent recommendations for a task',
    body: { task: 'Review this code for security issues', count: 3 },
  },
  { method: 'GET', path: '/api/capabilities', description: 'Get API capabilities and version' },
  { method: 'GET', path: '/health/ready', description: 'Health check endpoint' },
];

export const ApiPlayground: React.FC = () => {
  const [selectedEndpoint, setSelectedEndpoint] = useState<Endpoint>(ENDPOINTS[0]);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://api.aragora.ai');
  const [requestBody, setRequestBody] = useState(JSON.stringify(ENDPOINTS[0].body || {}, null, 2));
  const [pathParams, setPathParams] = useState<Record<string, string>>({});
  const [queryParams, setQueryParams] = useState<Record<string, string>>({});
  const [requestState, setRequestState] = useState<RequestState>({
    loading: false,
    response: null,
    error: null,
    duration: null,
    status: null,
  });

  const handleEndpointChange = useCallback((endpoint: Endpoint) => {
    setSelectedEndpoint(endpoint);
    setRequestBody(JSON.stringify(endpoint.body || {}, null, 2));
    setPathParams({});
    setQueryParams({});
  }, []);

  const buildUrl = useCallback(() => {
    let url = selectedEndpoint.path;

    // Replace path parameters
    Object.entries(pathParams).forEach(([key, value]) => {
      url = url.replace(`{${key}}`, encodeURIComponent(value));
    });

    // Add query parameters
    const queryString = Object.entries(queryParams)
      .filter(([, value]) => value)
      .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
      .join('&');

    if (queryString) {
      url += `?${queryString}`;
    }

    return `${baseUrl}${url}`;
  }, [selectedEndpoint, baseUrl, pathParams, queryParams]);

  const executeRequest = useCallback(async () => {
    setRequestState({ loading: true, response: null, error: null, duration: null, status: null });

    const startTime = performance.now();
    const url = buildUrl();

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };

      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`;
      }

      const options: RequestInit = { method: selectedEndpoint.method, headers };

      if (['POST', 'PUT', 'PATCH'].includes(selectedEndpoint.method) && requestBody) {
        options.body = requestBody;
      }

      const response = await fetch(url, options);
      const duration = performance.now() - startTime;

      let data;
      const contentType = response.headers.get('content-type');
      if (contentType?.includes('application/json')) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      setRequestState({
        loading: false,
        response: data,
        error: null,
        duration: Math.round(duration),
        status: response.status,
      });
    } catch (err) {
      const duration = performance.now() - startTime;
      setRequestState({
        loading: false,
        response: null,
        error: err instanceof Error ? err.message : 'Request failed',
        duration: Math.round(duration),
        status: null,
      });
    }
  }, [buildUrl, selectedEndpoint, apiKey, requestBody]);

  const getMethodColor = (method: string) => {
    const colors: Record<string, string> = {
      GET: 'bg-green-500',
      POST: 'bg-blue-500',
      PUT: 'bg-yellow-500',
      DELETE: 'bg-red-500',
      PATCH: 'bg-purple-500',
    };
    return colors[method] || 'bg-gray-500';
  };

  return (
    <div className="flex flex-col h-full bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">API Playground</h1>
        <p className="text-gray-600 dark:text-gray-400">Test Aragora API endpoints interactively</p>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar - Endpoints */}
        <div className="w-80 border-r border-gray-200 dark:border-gray-700 overflow-y-auto">
          <div className="p-4">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Endpoints
            </h2>
            <div className="space-y-1">
              {ENDPOINTS.map((endpoint, idx) => (
                <button
                  key={idx}
                  onClick={() => handleEndpointChange(endpoint)}
                  className={`w-full text-left p-2 rounded-lg flex items-center gap-2 transition-colors ${
                    selectedEndpoint === endpoint
                      ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300'
                      : 'hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300'
                  }`}
                >
                  <span
                    className={`${getMethodColor(endpoint.method)} text-white text-xs px-2 py-0.5 rounded font-theme-data`}
                  >
                    {endpoint.method}
                  </span>
                  <span className="text-sm truncate">{endpoint.path}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Configuration */}
          <div className="p-4 border-b border-gray-200 dark:border-gray-700 space-y-4">
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Base URL
                </label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                />
              </div>
              <div className="flex-1">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  API Key
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter your API key"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                />
              </div>
            </div>

            {/* URL Preview */}
            <div className="flex items-center gap-2">
              <span
                className={`${getMethodColor(selectedEndpoint.method)} text-white px-3 py-1 rounded font-theme-data text-sm`}
              >
                {selectedEndpoint.method}
              </span>
              <code className="flex-1 bg-gray-100 dark:bg-gray-800 px-3 py-1 rounded text-sm text-gray-700 dark:text-gray-300">
                {buildUrl()}
              </code>
              <button
                onClick={executeRequest}
                disabled={requestState.loading}
                className="px-4 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg font-medium transition-colors"
              >
                {requestState.loading ? 'Sending...' : 'Send'}
              </button>
            </div>
          </div>

          {/* Request/Response panels */}
          <div className="flex-1 flex overflow-hidden">
            {/* Request panel */}
            <div className="w-1/2 border-r border-gray-200 dark:border-gray-700 flex flex-col">
              <div className="p-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Request Body
                </h3>
              </div>
              <div className="flex-1 p-4 overflow-auto">
                {['POST', 'PUT', 'PATCH'].includes(selectedEndpoint.method) ? (
                  <textarea
                    value={requestBody}
                    onChange={(e) => setRequestBody(e.target.value)}
                    className="w-full h-full font-theme-data text-sm p-2 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded text-gray-900 dark:text-white resize-none"
                    placeholder="Request body (JSON)"
                  />
                ) : (
                  <p className="text-gray-500 dark:text-gray-400 text-sm">
                    No request body for {selectedEndpoint.method} requests
                  </p>
                )}
              </div>
            </div>

            {/* Response panel */}
            <div className="w-1/2 flex flex-col">
              <div className="p-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Response</h3>
                {requestState.status !== null && (
                  <div className="flex items-center gap-2 text-sm">
                    <span
                      className={`px-2 py-0.5 rounded ${
                        requestState.status < 300
                          ? 'bg-green-100 text-green-700'
                          : requestState.status < 400
                            ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-red-100 text-red-700'
                      }`}
                    >
                      {requestState.status}
                    </span>
                    {requestState.duration && (
                      <span className="text-gray-500">{requestState.duration}ms</span>
                    )}
                  </div>
                )}
              </div>
              <div className="flex-1 p-4 overflow-auto">
                {requestState.loading && (
                  <div className="flex items-center justify-center h-full">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  </div>
                )}
                {requestState.error && (
                  <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-4">
                    <p className="text-red-700 dark:text-red-400">{requestState.error}</p>
                  </div>
                )}
                {requestState.response !== null && requestState.response !== undefined && (
                  <pre className="font-theme-data text-sm bg-gray-100 dark:bg-gray-800 p-4 rounded overflow-auto text-gray-900 dark:text-white">
                    {JSON.stringify(requestState.response, null, 2)}
                  </pre>
                )}
                {!requestState.loading && !requestState.error && !requestState.response && (
                  <p className="text-gray-500 dark:text-gray-400 text-sm">
                    Click "Send" to execute the request
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ApiPlayground;
