'use client';

import { useState } from 'react';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MCPToolParam {
  type: string;
  required: boolean;
  default: unknown;
}

interface MCPTool {
  name: string;
  description: string;
  parameters: Record<string, MCPToolParam>;
}

interface MCPToolsResponse {
  tools: MCPTool[];
  count: number;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ToolCard({ tool }: { tool: MCPTool }) {
  const [expanded, setExpanded] = useState(false);
  const paramKeys = Object.keys(tool.parameters);
  const requiredParams = paramKeys.filter((k) => tool.parameters[k].required);

  return (
    <div className="border border-[var(--border)] rounded bg-[var(--surface)] hover:border-[var(--acid-green)]/40 transition-colors">
      <button
        className="w-full text-left px-4 py-3 flex items-start justify-between gap-4"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0">
          <span className="font-mono text-sm text-[var(--acid-green)]">{tool.name}</span>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 truncate">{tool.description}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {paramKeys.length > 0 && (
            <span className="text-xs font-mono text-[var(--text-muted)] border border-[var(--border)] rounded px-1.5 py-0.5">
              {paramKeys.length} param{paramKeys.length !== 1 ? 's' : ''}
            </span>
          )}
          <span className="text-[var(--text-muted)] text-xs">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-[var(--border)] pt-3">
          <p className="text-sm text-[var(--text)] mb-3">{tool.description}</p>

          {paramKeys.length > 0 ? (
            <div>
              <p className="text-xs font-mono text-[var(--text-muted)] mb-2 uppercase tracking-wider">
                Parameters
              </p>
              <div className="space-y-1.5">
                {paramKeys.map((key) => {
                  const p = tool.parameters[key];
                  return (
                    <div key={key} className="flex items-baseline gap-2 text-xs font-mono">
                      <span
                        className={
                          p.required ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'
                        }
                      >
                        {key}
                      </span>
                      <span className="text-[var(--text-muted)]">{p.type}</span>
                      {p.required && (
                        <span className="text-[var(--accent)] text-[10px]">required</span>
                      )}
                      {!p.required && p.default !== undefined && p.default !== null && (
                        <span className="text-[var(--text-muted)] text-[10px]">
                          default: {String(p.default)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <p className="text-xs text-[var(--text-muted)] font-mono">No parameters</p>
          )}

          {requiredParams.length > 0 && (
            <div className="mt-3 pt-3 border-t border-[var(--border)]">
              <p className="text-xs font-mono text-[var(--text-muted)] mb-1">Required</p>
              <div className="flex flex-wrap gap-1">
                {requiredParams.map((k) => (
                  <span
                    key={k}
                    className="text-[10px] font-mono bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded px-1.5 py-0.5"
                  >
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MCPToolsPage() {
  const [search, setSearch] = useState('');

  const { data, error, isLoading } = useSWRFetch<MCPToolsResponse>('/api/v1/mcp/tools');

  const tools: MCPTool[] = data?.tools ?? [];
  const filtered = search.trim()
    ? tools.filter(
        (t) =>
          t.name.toLowerCase().includes(search.toLowerCase()) ||
          t.description.toLowerCase().includes(search.toLowerCase()),
      )
    : tools;

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {/* Header */}
      <div className="border-b border-[var(--border)] bg-[var(--surface)]/50">
        <div className="container mx-auto px-4 py-10">
          <h1 className="text-2xl md:text-3xl font-mono text-[var(--acid-green)] mb-3">
            {'>'} MCP TOOL DISCOVERY
          </h1>
          <p className="text-sm text-[var(--text-muted)] font-mono max-w-2xl">
            Available MCP tools fetched live from{' '}
            <span className="text-[var(--text)]">/api/v1/mcp/tools</span>.{' '}
            {data ? `${data.count} tools registered.` : ''}
          </p>
        </div>
      </div>

      <div className="container mx-auto px-4 py-6">
        {/* Search */}
        <div className="mb-6">
          <input
            type="text"
            placeholder="Filter tools..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full max-w-md bg-[var(--surface)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]/60"
          />
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="text-sm font-mono text-[var(--text-muted)] py-8">
            Loading tools...
          </div>
        )}

        {/* Error */}
        {error && !isLoading && (
          <div className="border border-red-500/40 bg-red-500/10 rounded p-4 text-sm font-mono text-red-400">
            Failed to load tools: {error.message}
          </div>
        )}

        {/* Tool list */}
        {!isLoading && !error && (
          <>
            <p className="text-xs text-[var(--text-muted)] font-mono mb-4">
              {filtered.length === tools.length
                ? `${tools.length} tools`
                : `${filtered.length} of ${tools.length} tools`}
            </p>
            <div className="space-y-2">
              {filtered.map((tool) => (
                <ToolCard key={tool.name} tool={tool} />
              ))}
              {filtered.length === 0 && (
                <p className="text-sm text-[var(--text-muted)] font-mono py-4">
                  No tools match &ldquo;{search}&rdquo;.
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
