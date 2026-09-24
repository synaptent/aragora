'use client';

import { useState, useMemo } from 'react';
import type { InputMode } from '@/hooks/useCommandCenter';

interface BrainDumpInputProps {
  onSubmit: (text: string, mode: InputMode) => void;
  loading: boolean;
}

export function BrainDumpInput({ onSubmit, loading }: BrainDumpInputProps) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState<InputMode>('text');

  const stats = useMemo(() => {
    const words = text.trim().split(/\s+/).filter(Boolean).length;
    const lines = text.split('\n').filter((l) => l.trim()).length;
    const estimatedNodes =
      mode === 'list'
        ? lines
        : mode === 'json'
          ? (() => {
              try {
                return Array.isArray(JSON.parse(text)) ? JSON.parse(text).length : 1;
              } catch {
                return 0;
              }
            })()
          : Math.max(1, Math.ceil(words / 15));
    return { words, lines, estimatedNodes };
  }, [text, mode]);

  const modes: { id: InputMode; label: string; placeholder: string }[] = [
    {
      id: 'text',
      label: 'Free Text',
      placeholder:
        'Paste your ideas, brain dump, goals, or questions here...\n\nWrite freely - the AI will extract key ideas, cluster related concepts, set goals, decompose into tasks, and assign agents automatically.',
    },
    {
      id: 'list',
      label: 'Structured List',
      placeholder:
        '- Improve error handling in the API layer\n- Add rate limiting to public endpoints\n- Refactor authentication to support SSO\n- Create dashboard for monitoring agent performance\n- Write integration tests for the pipeline',
    },
    {
      id: 'json',
      label: 'Import JSON',
      placeholder:
        '[\n  "Improve error handling in the API layer",\n  "Add rate limiting to public endpoints",\n  "Refactor authentication to support SSO"\n]',
    },
  ];

  const activeMode = modes.find((m) => m.id === mode) || modes[0];

  return (
    <div className="w-full max-w-3xl space-y-4">
      {/* Header */}
      <div className="text-center space-y-2">
        <h1 className="text-2xl font-theme-data font-bold text-[var(--accent)]">Command Center</h1>
        <p className="text-text-muted font-theme-data text-sm">
          Dump your ideas. Watch AI build execution plans.
        </p>
      </div>

      {/* Mode Tabs */}
      <div className="flex gap-1 bg-surface rounded-lg p-1 border border-border">
        {modes.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={`flex-1 px-3 py-2 text-sm font-theme-data rounded transition-colors ${
              mode === m.id
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30'
                : 'text-text-muted hover:text-text hover:bg-bg'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Textarea */}
      <div className="relative">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={activeMode.placeholder}
          className="w-full min-h-[200px] bg-surface text-text font-theme-data text-sm p-4 rounded-lg border border-border resize-y focus:outline-none focus:border-[var(--accent)]/50 focus:ring-1 focus:ring-acid-green/20 placeholder:text-text-muted/50"
          disabled={loading}
        />
      </div>

      {/* Stats Bar */}
      <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
        <div className="flex gap-4">
          <span>{stats.words} words</span>
          <span>{stats.lines} lines</span>
          <span>~{stats.estimatedNodes} nodes</span>
        </div>
        <div>
          {mode === 'json' &&
            text.trim() &&
            (() => {
              try {
                JSON.parse(text);
                return <span className="text-emerald-400">Valid JSON</span>;
              } catch {
                return <span className="text-red-400">Invalid JSON</span>;
              }
            })()}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <button
          onClick={() => onSubmit(text, mode)}
          disabled={!text.trim() || loading}
          className="flex-1 px-6 py-3 bg-emerald-600 text-white font-theme-data font-bold text-lg rounded-lg hover:bg-emerald-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Processing...
            </span>
          ) : (
            'GO'
          )}
        </button>
        <button
          onClick={() => onSubmit(text, mode)}
          disabled={!text.trim() || loading}
          className="px-6 py-3 border border-indigo-500/50 text-indigo-400 font-theme-data text-sm rounded-lg hover:bg-indigo-500/10 transition-colors disabled:opacity-50"
        >
          Step by Step
        </button>
      </div>
    </div>
  );
}
