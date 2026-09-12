'use client';

import { useState } from 'react';

type Platform = 'claude-desktop' | 'cursor' | 'manual';

const PLATFORMS: { key: Platform; label: string; icon: string }[] = [
  { key: 'claude-desktop', label: 'Claude Desktop', icon: 'A' },
  { key: 'cursor', label: 'Cursor', icon: 'C' },
  { key: 'manual', label: 'Manual / Other', icon: '>' },
];

/**
 * MCP connection guide for setting up Aragora tools in AI coding assistants.
 */
export function ConnectionGuide() {
  const [platform, setPlatform] = useState<Platform>('claude-desktop');

  return (
    <div className="space-y-6">
      {/* Platform selector */}
      <div className="flex gap-2">
        {PLATFORMS.map((p) => (
          <button
            key={p.key}
            onClick={() => setPlatform(p.key)}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-theme-data border transition-colors ${
              platform === p.key
                ? 'text-[var(--acid-green)] border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                : 'text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/50'
            }`}
          >
            <span className="font-bold">{p.icon}</span>
            {p.label}
          </button>
        ))}
      </div>

      {/* Instructions */}
      <div className="border border-[var(--border)] bg-[var(--surface)]">
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
            Setup Guide: {PLATFORMS.find((p) => p.key === platform)?.label}
          </h3>
        </div>

        <div className="p-4 space-y-4">
          {platform === 'claude-desktop' && <ClaudeDesktopGuide />}
          {platform === 'cursor' && <CursorGuide />}
          {platform === 'manual' && <ManualGuide />}
        </div>
      </div>
    </div>
  );
}

function ClaudeDesktopGuide() {
  return (
    <>
      <Step n={1} title="Install Aragora MCP server">
        <CodeBlock code="pip install aragora" />
      </Step>

      <Step n={2} title="Add to Claude Desktop config">
        <p className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
          Edit{' '}
          <code className="text-[var(--acid-cyan)]">
            ~/Library/Application Support/Claude/claude_desktop_config.json
          </code>{' '}
          (macOS) or{' '}
          <code className="text-[var(--acid-cyan)]">
            %APPDATA%/Claude/claude_desktop_config.json
          </code>{' '}
          (Windows):
        </p>
        <CodeBlock
          code={`{
  "mcpServers": {
    "aragora": {
      "command": "python",
      "args": ["-m", "aragora.mcp"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here",
        "ARAGORA_API_URL": "http://localhost:8080"
      }
    }
  }
}`}
        />
      </Step>

      <Step n={3} title="Restart Claude Desktop">
        <p className="text-xs font-theme-data text-[var(--text-muted)]">
          Close and reopen Claude Desktop. You should see Aragora tools available in the tool
          picker. Try asking Claude: &quot;Run a debate about whether we should use
          Kubernetes&quot;.
        </p>
      </Step>
    </>
  );
}

function CursorGuide() {
  return (
    <>
      <Step n={1} title="Install Aragora MCP server">
        <CodeBlock code="pip install aragora" />
      </Step>

      <Step n={2} title="Add to Cursor MCP config">
        <p className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
          Edit <code className="text-[var(--acid-cyan)]">~/.cursor/mcp.json</code>:
        </p>
        <CodeBlock
          code={`{
  "mcpServers": {
    "aragora": {
      "command": "python",
      "args": ["-m", "aragora.mcp"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here",
        "ARAGORA_API_URL": "http://localhost:8080"
      }
    }
  }
}`}
        />
      </Step>

      <Step n={3} title="Reload Cursor">
        <p className="text-xs font-theme-data text-[var(--text-muted)]">
          Restart Cursor or reload the window (Cmd+Shift+P / Ctrl+Shift+P, then &quot;Reload
          Window&quot;). Aragora tools will appear in Cursor&apos;s tool palette.
        </p>
      </Step>
    </>
  );
}

function ManualGuide() {
  return (
    <>
      <Step n={1} title="Start the MCP server">
        <CodeBlock code="python -m aragora.mcp --transport stdio" />
        <p className="text-xs font-theme-data text-[var(--text-muted)] mt-2">
          Or for HTTP transport:
        </p>
        <CodeBlock code="python -m aragora.mcp --transport sse --port 3001" />
      </Step>

      <Step n={2} title="Configure your MCP client">
        <p className="text-xs font-theme-data text-[var(--text-muted)]">
          Point your MCP-compatible client to the server. The server exposes 60+ tools across
          debate, audit, knowledge, workflow, and platform categories.
        </p>
      </Step>

      <Step n={3} title="Environment variables">
        <CodeBlock
          code={`# Required (at least one AI provider)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Optional
ARAGORA_API_URL=http://localhost:8080
OPENROUTER_API_KEY=sk-or-...
MISTRAL_API_KEY=...`}
        />
      </Step>
    </>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <div className="shrink-0 w-6 h-6 flex items-center justify-center text-xs font-theme-data font-bold text-[var(--acid-green)] border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10">
        {n}
      </div>
      <div className="flex-1">
        <h4 className="text-sm font-theme-data text-[var(--text)] font-bold mb-2">{title}</h4>
        {children}
      </div>
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API not available
    }
  };

  return (
    <div className="relative group">
      <pre className="bg-[var(--bg)] border border-[var(--border)] p-3 text-xs font-theme-data text-[var(--text)] overflow-x-auto">
        {code}
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-[10px] font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:border-[var(--acid-green)]/30 transition-colors opacity-0 group-hover:opacity-100"
      >
        {copied ? 'COPIED' : 'COPY'}
      </button>
    </div>
  );
}
