'use client';

import { useState } from 'react';
import type { MCPTool } from '@/lib/mcp-tools-registry';

const CATEGORY_COLORS: Record<string, string> = {
  Debate: 'text-[var(--acid-green)] border-[var(--acid-green)]/40 bg-[var(--acid-green)]/10',
  Agent: 'text-amber-400 border-amber-400/40 bg-amber-400/10',
  Memory: 'text-violet-400 border-violet-400/40 bg-violet-400/10',
  Knowledge: 'text-cyan-400 border-cyan-400/40 bg-cyan-400/10',
  Verification: 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10',
  Workflow: 'text-blue-400 border-blue-400/40 bg-blue-400/10',
  Evidence: 'text-orange-400 border-orange-400/40 bg-orange-400/10',
  Platform: 'text-rose-400 border-rose-400/40 bg-rose-400/10',
  Canvas: 'text-pink-400 border-pink-400/40 bg-pink-400/10',
  Pipeline: 'text-indigo-400 border-indigo-400/40 bg-indigo-400/10',
  Codebase: 'text-yellow-400 border-yellow-400/40 bg-yellow-400/10',
  'Self-Improve': 'text-teal-400 border-teal-400/40 bg-teal-400/10',
};

interface ToolCardProps {
  tool: MCPTool;
  expanded?: boolean;
  onToggle?: () => void;
}

export function ToolCard({ tool, expanded, onToggle }: ToolCardProps) {
  const [copied, setCopied] = useState(false);
  const colorClass =
    CATEGORY_COLORS[tool.category] ||
    'text-[var(--text-muted)] border-[var(--border)] bg-[var(--surface)]';

  const requiredParams = tool.parameters.filter((p) => p.required);
  const optionalParams = tool.parameters.filter((p) => !p.required);

  const snippet = buildSnippet(tool);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable
    }
  };

  return (
    <div
      className={`border bg-[var(--surface)]/50 rounded transition-colors ${
        expanded
          ? 'border-[var(--acid-green)]/50'
          : 'border-[var(--border)] hover:border-[var(--acid-green)]/30'
      }`}
    >
      {/* Collapsed header — always visible */}
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex items-center justify-between gap-3"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-theme-data text-sm text-[var(--acid-green)] font-bold truncate">
              {tool.name}
            </span>
            <span
              className={`shrink-0 px-1.5 py-0.5 text-[10px] font-theme-data border rounded ${colorClass}`}
            >
              {tool.category}
            </span>
          </div>
          <p className="text-xs font-theme-data text-[var(--text-muted)] mt-1 truncate">
            {tool.description}
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
            {tool.parameters.length} param{tool.parameters.length !== 1 ? 's' : ''}
          </span>
          <span className="text-xs font-theme-data text-[var(--text-muted)]">
            {expanded ? '-' : '+'}
          </span>
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-[var(--border)]">
          <p className="text-xs font-theme-data text-[var(--text)] pt-3">{tool.description}</p>

          {/* Parameter table */}
          {tool.parameters.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] font-theme-data">
                <thead>
                  <tr className="text-[var(--text-muted)] border-b border-[var(--border)]">
                    <th className="text-left py-1.5 pr-3">Parameter</th>
                    <th className="text-left py-1.5 pr-3">Type</th>
                    <th className="text-left py-1.5 pr-3">Required</th>
                    <th className="text-left py-1.5">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {requiredParams.map((p) => (
                    <tr key={p.name} className="border-b border-[var(--border)]/50">
                      <td className="py-1.5 pr-3 text-[var(--acid-green)]">{p.name}</td>
                      <td className="py-1.5 pr-3 text-[var(--text-muted)]">{p.type}</td>
                      <td className="py-1.5 pr-3 text-amber-400">yes</td>
                      <td className="py-1.5 text-[var(--text-muted)]">{p.description}</td>
                    </tr>
                  ))}
                  {optionalParams.map((p) => (
                    <tr key={p.name} className="border-b border-[var(--border)]/50">
                      <td className="py-1.5 pr-3 text-[var(--text)]">{p.name}</td>
                      <td className="py-1.5 pr-3 text-[var(--text-muted)]">{p.type}</td>
                      <td className="py-1.5 pr-3 text-[var(--text-muted)]">no</td>
                      <td className="py-1.5 text-[var(--text-muted)]">{p.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* SDK snippet */}
          <div className="relative group">
            <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-1">
              SDK Usage
            </div>
            <pre className="bg-[var(--bg)] border border-[var(--border)] rounded p-3 text-xs font-theme-data text-[var(--text)] overflow-x-auto">
              {snippet}
            </pre>
            <button
              onClick={handleCopy}
              className="absolute top-7 right-2 px-2 py-1 text-[10px] font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:border-[var(--acid-green)]/30 transition-colors opacity-0 group-hover:opacity-100"
            >
              {copied ? 'COPIED' : 'COPY'}
            </button>
          </div>

          {/* Execute button — Phase 2 */}
          <button
            disabled
            className="w-full py-2 text-xs font-theme-data border border-[var(--border)] rounded text-[var(--text-muted)] bg-[var(--surface)]/30 cursor-not-allowed flex items-center justify-center gap-2"
          >
            Execute
            <span className="px-1.5 py-0.5 text-[10px] border border-[var(--text-muted)]/30 rounded">
              COMING SOON
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

function buildSnippet(tool: MCPTool): string {
  const requiredParams = tool.parameters.filter((p) => p.required);
  if (requiredParams.length === 0) {
    return `const result = await mcp.call("${tool.name}");`;
  }
  const paramLines = requiredParams.map((p) => `  ${p.name}: ${placeholderForType(p.type)},`);
  return `const result = await mcp.call("${tool.name}", {\n${paramLines.join('\n')}\n});`;
}

function placeholderForType(type: string): string {
  switch (type) {
    case 'string':
      return '"..."';
    case 'number':
      return '10';
    case 'boolean':
      return 'true';
    case 'string[]':
      return '["agent_1", "agent_2"]';
    case 'object':
      return '{ /* ... */ }';
    default:
      return '"..."';
  }
}
