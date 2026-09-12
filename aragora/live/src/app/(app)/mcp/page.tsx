'use client';

import { useState } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ToolCatalog, MCP_TOOLS } from '@/components/mcp/ToolCatalog';
import { ConnectionGuide } from '@/components/mcp/ConnectionGuide';

type MCPTab = 'catalog' | 'setup';

export default function MCPPage() {
  const [tab, setTab] = useState<MCPTab>('catalog');

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        {/* Hero */}
        <div className="border-b border-[var(--acid-green)]/20 bg-[var(--surface)]/30">
          <div className="container mx-auto px-4 py-12">
            <h1 className="text-3xl md:text-4xl font-theme-data text-[var(--acid-green)] mb-4">
              {'>'} MCP TOOLS
            </h1>
            <p className="text-[var(--text-muted)] font-theme-data max-w-2xl">
              {MCP_TOOLS.length} tools for AI coding assistants. Connect Claude Desktop, Cursor, or
              any MCP-compatible client to get multi-agent debate, audit, knowledge, and workflow
              capabilities directly in your editor.
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-[var(--border)]">
          <div className="container mx-auto px-4">
            <div className="flex">
              {(
                [
                  { key: 'catalog', label: 'TOOL CATALOG' },
                  { key: 'setup', label: 'CONNECTION GUIDE' },
                ] as const
              ).map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`px-6 py-3 text-sm font-theme-data border-b-2 transition-colors ${
                    tab === t.key
                      ? 'text-[var(--acid-green)] border-[var(--acid-green)]'
                      : 'text-[var(--text-muted)] border-transparent hover:text-[var(--text)]'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-8">
          {tab === 'catalog' && <ToolCatalog />}
          {tab === 'setup' && <ConnectionGuide />}
        </div>
      </main>
    </>
  );
}
