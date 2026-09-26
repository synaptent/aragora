'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE_URL } from '@/config';

interface PluginManifest {
  name: string;
  version: string;
  description: string;
  capabilities: string[];
  requirements: string[];
  entry_point: string;
  timeout_seconds: number;
  max_memory_mb: number;
  requirements_satisfied?: boolean;
  missing_requirements?: string[];
}

interface PluginRunResult {
  success: boolean;
  plugin: string;
  output?: string;
  error?: string;
  duration_ms?: number;
  exit_code?: number;
}

interface PluginRunModalProps {
  plugin: PluginManifest;
  onClose: () => void;
  apiBase?: string;
}

export function PluginRunModal({ plugin, onClose, apiBase = API_BASE_URL }: PluginRunModalProps) {
  const [input, setInput] = useState('');
  const [targetPath, setTargetPath] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PluginRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !running) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, running]);

  // Handle click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node) && !running) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose, running]);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`${apiBase}/api/plugins/${plugin.name}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ input: input || undefined, target_path: targetPath || undefined }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run plugin');
    } finally {
      setRunning(false);
    }
  }, [apiBase, plugin.name, input, targetPath]);

  const requirementsNotMet = plugin.requirements_satisfied === false;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="plugin-modal-title"
    >
      <div
        ref={modalRef}
        className="w-full max-w-2xl mx-4 border border-[var(--accent)]/40 bg-surface shadow-2xl shadow-acid-green/10"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--accent)]/20 bg-bg/50">
          <div>
            <h2 id="plugin-modal-title" className="text-lg font-theme-data text-[var(--accent)]">
              {'>'} RUN PLUGIN: {plugin.name}
            </h2>
            <p className="text-xs font-theme-data text-text-muted mt-1">
              v{plugin.version} | {plugin.entry_point}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={running}
            aria-label="Close modal"
            className="text-text-muted hover:text-text transition-colors disabled:opacity-50 font-theme-data"
          >
            [X]
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Requirements Warning */}
          {requirementsNotMet && (
            <div className="p-3 border border-acid-red/30 bg-acid-red/10 text-xs font-theme-data text-acid-red">
              <div className="font-bold mb-1">REQUIREMENTS NOT MET</div>
              <div>Missing: {plugin.missing_requirements?.join(', ')}</div>
            </div>
          )}

          {/* Plugin Info */}
          <div className="grid grid-cols-2 gap-4 text-xs font-theme-data">
            <div className="p-3 border border-[var(--accent)]/20 bg-bg/30">
              <div className="text-text-muted mb-1">TIMEOUT</div>
              <div className="text-[var(--acid-cyan)]">{plugin.timeout_seconds}s</div>
            </div>
            <div className="p-3 border border-[var(--accent)]/20 bg-bg/30">
              <div className="text-text-muted mb-1">MAX MEMORY</div>
              <div className="text-[var(--acid-cyan)]">{plugin.max_memory_mb}MB</div>
            </div>
          </div>

          {/* Input Form */}
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-2">
                TARGET PATH (optional)
              </label>
              <input
                type="text"
                value={targetPath}
                onChange={(e) => setTargetPath(e.target.value)}
                placeholder="/path/to/analyze"
                disabled={running}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none disabled:opacity-50"
              />
            </div>
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-2">
                INPUT DATA (optional)
              </label>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Additional input for the plugin..."
                rows={3}
                disabled={running}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none resize-none disabled:opacity-50"
              />
            </div>
          </div>

          {/* Error Display */}
          {error && (
            <div className="p-3 border border-acid-red/30 bg-acid-red/10 text-xs font-theme-data text-acid-red">
              {'>'} ERROR: {error}
            </div>
          )}

          {/* Result Display */}
          {result && (
            <div
              className={`p-4 border ${result.success ? 'border-[var(--accent)]/30 bg-[var(--accent)]/5' : 'border-acid-red/30 bg-acid-red/5'}`}
            >
              <div className="flex items-center justify-between mb-3">
                <span
                  className={`text-xs font-theme-data ${result.success ? 'text-[var(--accent)]' : 'text-acid-red'}`}
                >
                  {result.success ? 'SUCCESS' : 'FAILED'}
                </span>
                {result.duration_ms !== undefined && (
                  <span className="text-xs font-theme-data text-text-muted">
                    {result.duration_ms}ms
                  </span>
                )}
              </div>
              {result.output && (
                <pre className="text-xs font-theme-data text-text bg-bg/50 p-3 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                  {result.output}
                </pre>
              )}
              {result.error && (
                <pre className="text-xs font-theme-data text-acid-red bg-bg/50 p-3 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                  {result.error}
                </pre>
              )}
              {result.exit_code !== undefined && result.exit_code !== 0 && (
                <div className="mt-2 text-xs font-theme-data text-text-muted">
                  Exit code: {result.exit_code}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--accent)]/20 bg-bg/30">
          <div className="text-xs font-theme-data text-text-muted">
            CLI: <code className="text-[var(--acid-cyan)]">aragora plugins run {plugin.name}</code>
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              disabled={running}
              aria-label="Close plugin runner"
              className="px-4 py-2 text-xs font-theme-data text-text-muted hover:text-text transition-colors disabled:opacity-50"
            >
              [CLOSE]
            </button>
            <button
              onClick={handleRun}
              disabled={running || requirementsNotMet}
              aria-busy={running}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {running ? 'RUNNING...' : 'RUN PLUGIN'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
