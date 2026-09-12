'use client';

import React, { useState, useMemo } from 'react';

export interface Parameter {
  name: string;
  in: 'path' | 'query' | 'header';
  required?: boolean;
  description?: string;
  default?: string;
}

export interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  path: string;
  description: string;
  group: string;
  parameters?: Parameter[];
  body?: Record<string, unknown>;
}

const METHOD_COLORS: Record<string, string> = {
  GET: 'text-emerald-400',
  POST: 'text-blue-400',
  PUT: 'text-amber-400',
  DELETE: 'text-red-400',
  PATCH: 'text-purple-400',
};

export const ENDPOINTS: Endpoint[] = [
  // Debates
  {
    method: 'POST',
    path: '/api/v2/debates',
    description: 'Create a new debate',
    group: 'Debates',
    body: { task: 'Should we use microservices?', agents: ['claude', 'openai'], rounds: 3 },
  },
  {
    method: 'GET',
    path: '/api/v2/debates',
    description: 'List all debates',
    group: 'Debates',
    parameters: [
      { name: 'limit', in: 'query', default: '20' },
      { name: 'offset', in: 'query', default: '0' },
    ],
  },
  {
    method: 'GET',
    path: '/api/v2/debates/{debate_id}',
    description: 'Get debate by ID',
    group: 'Debates',
    parameters: [{ name: 'debate_id', in: 'path', required: true }],
  },
  {
    method: 'GET',
    path: '/api/v2/debates/{debate_id}/receipt',
    description: 'Get debate receipt',
    group: 'Debates',
    parameters: [{ name: 'debate_id', in: 'path', required: true }],
  },
  // Agents
  { method: 'GET', path: '/api/v2/agents', description: 'List available agents', group: 'Agents' },
  {
    method: 'GET',
    path: '/api/v2/agents/{agent_id}',
    description: 'Get agent details',
    group: 'Agents',
    parameters: [{ name: 'agent_id', in: 'path', required: true }],
  },
  {
    method: 'GET',
    path: '/api/v2/agents/{agent_id}/stats',
    description: 'Get agent ELO stats',
    group: 'Agents',
    parameters: [{ name: 'agent_id', in: 'path', required: true }],
  },
  // Knowledge
  {
    method: 'POST',
    path: '/api/v2/knowledge/search',
    description: 'Semantic search across knowledge',
    group: 'Knowledge',
    body: { query: 'rate limiting best practices', limit: 10 },
  },
  {
    method: 'GET',
    path: '/api/v2/knowledge/stats',
    description: 'Knowledge base statistics',
    group: 'Knowledge',
  },
  // Health
  { method: 'GET', path: '/api/v2/health', description: 'Health check', group: 'System' },
  { method: 'GET', path: '/api/v2/health/ready', description: 'Readiness probe', group: 'System' },
  { method: 'GET', path: '/api/v2/metrics', description: 'Prometheus metrics', group: 'System' },
];

interface EndpointSelectorProps {
  selected: Endpoint;
  onSelect: (endpoint: Endpoint) => void;
}

export function EndpointSelector({ selected, onSelect }: EndpointSelectorProps) {
  const [search, setSearch] = useState('');

  const groups = useMemo(() => {
    const filtered = ENDPOINTS.filter(
      (e) =>
        e.path.toLowerCase().includes(search.toLowerCase()) ||
        e.description.toLowerCase().includes(search.toLowerCase()),
    );
    const map = new Map<string, Endpoint[]>();
    for (const ep of filtered) {
      const list = map.get(ep.group) || [];
      list.push(ep);
      map.set(ep.group, list);
    }
    return map;
  }, [search]);

  return (
    <div className="h-full flex flex-col bg-[var(--bg)]">
      <div className="p-3 border-b border-[var(--border)]">
        <input
          type="text"
          placeholder="Search endpoints..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-2 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]"
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {Array.from(groups.entries()).map(([group, endpoints]) => (
          <div key={group}>
            <div className="px-3 py-2 text-[10px] font-theme-data font-bold text-[var(--text-muted)] uppercase tracking-wider bg-[var(--surface)]/50">
              {group}
            </div>
            {endpoints.map((ep) => {
              const isSelected = selected.path === ep.path && selected.method === ep.method;
              return (
                <button
                  key={`${ep.method}-${ep.path}`}
                  onClick={() => onSelect(ep)}
                  className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
                    isSelected
                      ? 'border-[var(--acid-green)] bg-[var(--surface)]'
                      : 'border-transparent hover:bg-[var(--surface)]/50'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-[10px] font-theme-data font-bold ${METHOD_COLORS[ep.method] || 'text-gray-400'}`}
                    >
                      {ep.method}
                    </span>
                    <span className="text-xs font-theme-data text-[var(--text)] truncate">
                      {ep.path.replace('/api/v2', '')}
                    </span>
                  </div>
                  <p className="text-[10px] font-theme-data text-[var(--text-muted)] mt-0.5 truncate">
                    {ep.description}
                  </p>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
