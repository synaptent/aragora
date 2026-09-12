'use client';

import { useEffect, useRef } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useRightSidebar } from '@/context/RightSidebarContext';
import {
  useSandboxStore,
  STATUS_STYLES,
  LANGUAGE_CONFIG,
  type Language,
  type ExecutionResult,
} from '@/store/sandboxStore';

export default function SandboxPage() {
  const {
    code,
    language,
    currentExecution,
    executionHistory,
    isExecuting,
    executionError,
    config,
    poolStatus,
    setCode,
    setLanguage,
    execute,
    cancelExecution,
    clearResult,
    fetchConfig,
    fetchPoolStatus,
  } = useSandboxStore();

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { setContext, clearContext } = useRightSidebar();

  // Fetch config and pool status on mount
  useEffect(() => {
    fetchConfig();
    fetchPoolStatus();

    // Poll pool status every 30 seconds
    const interval = setInterval(fetchPoolStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchConfig, fetchPoolStatus]);

  // Set up right sidebar
  useEffect(() => {
    setContext({
      title: 'Code Sandbox',
      subtitle: 'Safe execution environment',
      statsContent: (
        <div className="space-y-3">
          {poolStatus && (
            <>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">Available</span>
                <span className="text-sm font-theme-data text-[var(--acid-green)]">
                  {poolStatus.available}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">In Use</span>
                <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
                  {poolStatus.in_use}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">Pool Health</span>
                <span
                  className={`text-sm font-theme-data ${poolStatus.healthy ? 'text-green-400' : 'text-red-400'}`}
                >
                  {poolStatus.healthy ? 'HEALTHY' : 'DEGRADED'}
                </span>
              </div>
            </>
          )}
          {config && (
            <>
              <div className="border-t border-[var(--border)] pt-3 mt-3">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-[var(--text-muted)]">Mode</span>
                  <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
                    {config.mode.toUpperCase()}
                  </span>
                </div>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">Timeout</span>
                <span className="text-sm font-theme-data text-[var(--text)]">
                  {config.resource_limits.max_execution_seconds}s
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">Memory</span>
                <span className="text-sm font-theme-data text-[var(--text)]">
                  {config.resource_limits.max_memory_mb}MB
                </span>
              </div>
            </>
          )}
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Executions</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">
              {executionHistory.length}
            </span>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <button
            onClick={execute}
            disabled={isExecuting || !code.trim()}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)] text-[var(--bg)] font-bold hover:bg-[var(--acid-green)]/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExecuting ? 'EXECUTING...' : 'RUN CODE'}
          </button>
          {isExecuting && currentExecution && (
            <button
              onClick={() => cancelExecution(currentExecution.execution_id)}
              className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors"
            >
              CANCEL
            </button>
          )}
          <button
            onClick={clearResult}
            disabled={!currentExecution}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors disabled:opacity-50"
          >
            CLEAR RESULT
          </button>
        </div>
      ),
    });

    return () => clearContext();
  }, [
    poolStatus,
    config,
    executionHistory.length,
    isExecuting,
    code,
    currentExecution,
    execute,
    cancelExecution,
    clearResult,
    setContext,
    clearContext,
  ]);

  // Handle keyboard shortcut (Ctrl/Cmd + Enter to run)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!isExecuting && code.trim()) {
          execute();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isExecuting, code, execute]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="max-w-6xl mx-auto px-4 py-8">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">CODE SANDBOX</h1>
            <p className="text-text-muted text-sm font-theme-data">
              Execute code in an isolated environment with resource limits and policy enforcement.
            </p>
          </div>

          {/* Error Banner */}
          {executionError && (
            <div className="mb-4 border border-warning/30 bg-warning/10 p-3">
              <p className="text-warning text-sm font-theme-data">{executionError}</p>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Code Editor */}
            <div className="space-y-4">
              {/* Language Selector */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-theme-data text-text-muted">Language:</span>
                <div className="flex gap-1">
                  {(Object.keys(LANGUAGE_CONFIG) as Language[]).map((lang) => (
                    <button
                      key={lang}
                      onClick={() => setLanguage(lang)}
                      className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                        language === lang
                          ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/50'
                          : 'bg-surface text-text-muted border-border hover:border-[var(--accent)]/30'
                      }`}
                    >
                      {LANGUAGE_CONFIG[lang].label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Code Editor */}
              <div className="border border-[var(--accent)]/30 bg-surface/50">
                <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--accent)]/20 bg-surface/80">
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                    code{LANGUAGE_CONFIG[language].extension}
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">Ctrl+Enter to run</span>
                </div>
                <textarea
                  ref={textareaRef}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  disabled={isExecuting}
                  spellCheck={false}
                  className="w-full h-80 p-4 bg-bg text-text font-theme-data text-sm resize-none focus:outline-none disabled:opacity-50"
                  placeholder={LANGUAGE_CONFIG[language].placeholder}
                />
              </div>

              {/* Run Button (Mobile) */}
              <button
                onClick={execute}
                disabled={isExecuting || !code.trim()}
                className="lg:hidden w-full py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isExecuting ? 'EXECUTING...' : 'RUN CODE'}
              </button>
            </div>

            {/* Right: Execution Result */}
            <div className="space-y-4">
              {/* Current Result */}
              <div className="border border-[var(--accent)]/30 bg-surface/50">
                <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--accent)]/20 bg-surface/80">
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">OUTPUT</span>
                  {currentExecution && <StatusBadge status={currentExecution.status} />}
                </div>

                <div className="h-80 overflow-auto">
                  {isExecuting && !currentExecution && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="w-8 h-8 border-2 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin mx-auto mb-4" />
                        <p className="text-text-muted text-sm font-theme-data">Executing...</p>
                      </div>
                    </div>
                  )}

                  {!isExecuting && !currentExecution && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center text-text-muted">
                        <p className="text-sm font-theme-data">Run code to see output</p>
                        <p className="text-xs font-theme-data mt-2 opacity-50">Press Ctrl+Enter</p>
                      </div>
                    </div>
                  )}

                  {currentExecution && <ExecutionOutput result={currentExecution} />}
                </div>
              </div>

              {/* Execution Details */}
              {currentExecution && (
                <div className="border border-[var(--acid-cyan)]/30 bg-surface/50 p-4">
                  <h3 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 uppercase">
                    Execution Details
                  </h3>
                  <div className="grid grid-cols-2 gap-3 text-xs font-theme-data">
                    <div>
                      <span className="text-text-muted">Duration</span>
                      <div className="text-text">
                        {currentExecution.duration_seconds.toFixed(3)}s
                      </div>
                    </div>
                    <div>
                      <span className="text-text-muted">Memory</span>
                      <div className="text-text">
                        {currentExecution.memory_used_mb.toFixed(1)} MB
                      </div>
                    </div>
                    <div>
                      <span className="text-text-muted">Exit Code</span>
                      <div
                        className={
                          currentExecution.exit_code === 0 ? 'text-green-400' : 'text-red-400'
                        }
                      >
                        {currentExecution.exit_code}
                      </div>
                    </div>
                    <div>
                      <span className="text-text-muted">ID</span>
                      <div className="text-text truncate">{currentExecution.execution_id}</div>
                    </div>
                  </div>

                  {/* Policy Violations */}
                  {currentExecution.policy_violations.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-[var(--acid-cyan)]/20">
                      <span className="text-xs text-orange-400">Policy Violations:</span>
                      <ul className="mt-1 space-y-1">
                        {currentExecution.policy_violations.map((v, i) => (
                          <li key={i} className="text-xs text-text-muted">
                            • {v}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Files Created */}
                  {currentExecution.files_created.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-[var(--acid-cyan)]/20">
                      <span className="text-xs text-[var(--accent)]">Files Created:</span>
                      <ul className="mt-1 space-y-1">
                        {currentExecution.files_created.map((f, i) => (
                          <li key={i} className="text-xs text-text-muted font-theme-data">
                            • {f}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Execution History */}
          {executionHistory.length > 1 && (
            <div className="mt-8">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
                  Recent Executions ({executionHistory.length})
                </h2>
              </div>

              <div className="grid gap-2">
                {executionHistory.slice(1, 6).map((result) => (
                  <HistoryItem key={result.execution_id} result={result} />
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}

// ============================================================================
// Helper Components
// ============================================================================

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status as keyof typeof STATUS_STYLES] || STATUS_STYLES.pending;
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data ${style.color} ${style.bgColor} border border-current/30`}
    >
      {style.label}
    </span>
  );
}

function ExecutionOutput({ result }: { result: ExecutionResult }) {
  return (
    <div className="p-4 space-y-4">
      {/* Stdout */}
      {result.stdout && (
        <div>
          <div className="text-xs text-[var(--accent)] mb-1">stdout</div>
          <pre className="p-3 bg-bg/50 border border-[var(--accent)]/10 text-sm font-theme-data text-text whitespace-pre-wrap overflow-x-auto max-h-40">
            {result.stdout}
          </pre>
        </div>
      )}

      {/* Stderr */}
      {result.stderr && (
        <div>
          <div className="text-xs text-red-400 mb-1">stderr</div>
          <pre className="p-3 bg-red-500/5 border border-red-500/20 text-sm font-theme-data text-red-300 whitespace-pre-wrap overflow-x-auto max-h-40">
            {result.stderr}
          </pre>
        </div>
      )}

      {/* Error Message */}
      {result.error_message && (
        <div>
          <div className="text-xs text-warning mb-1">error</div>
          <pre className="p-3 bg-warning/10 border border-warning/20 text-sm font-theme-data text-warning whitespace-pre-wrap">
            {result.error_message}
          </pre>
        </div>
      )}

      {/* No output */}
      {!result.stdout && !result.stderr && !result.error_message && (
        <div className="text-center text-text-muted py-8">
          <p className="text-sm font-theme-data">No output</p>
        </div>
      )}
    </div>
  );
}

function HistoryItem({ result }: { result: ExecutionResult }) {
  return (
    <div className="flex items-center gap-4 px-4 py-2 border border-[var(--accent)]/10 bg-surface/30 hover:bg-surface/50 transition-colors">
      <StatusBadge status={result.status} />
      <span className="text-xs font-theme-data text-text-muted flex-1 truncate">
        {result.execution_id}
      </span>
      <span className="text-xs font-theme-data text-text-muted">
        {result.duration_seconds.toFixed(3)}s
      </span>
      <span
        className={`text-xs font-theme-data ${result.exit_code === 0 ? 'text-green-400' : 'text-red-400'}`}
      >
        exit {result.exit_code}
      </span>
    </div>
  );
}
