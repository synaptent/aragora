'use client';

import { useState, useCallback, useEffect } from 'react';
import { getRuntimeBackendConfig } from '@/components/BackendSelector';
import { useOnboardingStore } from '@/store';
import { useDebateWebSocket } from '@/hooks/debate-websocket/useDebateWebSocket';

type ReceiptListItem = {
  receipt_id?: string;
  id?: string;
  verdict?: string;
  confidence?: number;
  risk_level?: string;
  created_at?: number;
};

type ReceiptFull = Record<string, unknown> & {
  receipt_id?: string;
  verdict?: string;
  confidence?: number;
  risk_level?: string;
  risk_score?: number;
};

export function FirstDebateStep() {
  const apiBase = getRuntimeBackendConfig().config.api;
  const {
    selectedTemplate,
    firstDebateTopic,
    firstDebateId,
    firstReceiptId,
    debateStatus,
    debateError,
    setFirstDebateTopic,
    setFirstDebateId,
    setFirstReceiptId,
    setDebateStatus,
    setDebateError,
    updateProgress,
  } = useOnboardingStore();

  const [localError, setLocalError] = useState<string | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ReceiptFull | null>(null);

  // Use WebSocket for real-time debate progress
  const { status: wsStatus, messages: wsMessages } = useDebateWebSocket({
    debateId: firstDebateId || '',
    enabled: !!firstDebateId && debateStatus === 'running',
  });

  // Update debate status based on WebSocket events
  useEffect(() => {
    if (wsStatus === 'complete' && debateStatus === 'running') {
      setDebateStatus('completed');
      updateProgress({ firstDebateCompleted: true });
    }
    if (wsStatus === 'error') {
      setDebateError('Debate connection lost');
      setDebateStatus('error');
    }
  }, [wsStatus, debateStatus, setDebateStatus, setDebateError, updateProgress]);

  const _pollReceiptIdForDebate = useCallback(
    async (debateId: string, signal: AbortSignal) => {
      const maxAttempts = 12;
      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        if (signal.aborted) return null;

        const response = await fetch(
          `${apiBase}/api/v2/receipts?debate_id=${encodeURIComponent(debateId)}&limit=1&offset=0`,
          { signal },
        );

        if (!response.ok) {
          // Auth errors are actionable; others are usually transient.
          if (response.status === 401 || response.status === 403) {
            throw new Error('Not authorized to view receipts');
          }
          throw new Error(`Failed to list receipts (HTTP ${response.status})`);
        }

        const data = await response.json().catch(() => ({}));
        const receipts: ReceiptListItem[] = Array.isArray(data?.receipts) ? data.receipts : [];
        const first = receipts[0];
        const receiptId = (first?.receipt_id || first?.id || '').trim();
        if (receiptId) return receiptId;

        // Backoff: 0.5s, 1s, 1.5s, ... capped at 4s
        const waitMs = Math.min(4000, 500 * attempt);
        await new Promise((r) => setTimeout(r, waitMs));
      }

      return null;
    },
    [apiBase],
  );

  const _pollReceiptById = useCallback(
    async (receiptId: string, signal: AbortSignal) => {
      const maxAttempts = 12;
      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        if (signal.aborted) return null;

        const response = await fetch(
          `${apiBase}/api/v2/receipts/${encodeURIComponent(receiptId)}`,
          { signal },
        );

        if (response.status === 404) {
          const waitMs = Math.min(4000, 500 * attempt);
          await new Promise((r) => setTimeout(r, waitMs));
          continue;
        }

        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            throw new Error('Not authorized to view receipts');
          }
          throw new Error(`Failed to fetch receipt (HTTP ${response.status})`);
        }

        return (await response.json().catch(() => ({}))) as ReceiptFull;
      }

      return null;
    },
    [apiBase],
  );

  const fetchReceipt = useCallback(async () => {
    if (!firstDebateId || debateStatus !== 'completed') return;

    setReceiptLoading(true);
    setReceiptError(null);

    const controller = new AbortController();

    try {
      let receiptId = firstReceiptId;

      // If debate creation didn't return a receipt_id, locate it by debate_id.
      if (!receiptId) {
        receiptId = await _pollReceiptIdForDebate(firstDebateId, controller.signal);
        if (receiptId) setFirstReceiptId(receiptId);
      }

      if (!receiptId) {
        throw new Error('Receipt is still generating. Try again in a moment.');
      }

      const full = await _pollReceiptById(receiptId, controller.signal);
      if (!full) {
        throw new Error('Receipt is still generating. Try again in a moment.');
      }

      setReceipt(full);
      updateProgress({ receiptViewed: true });
    } catch (err) {
      setReceiptError(err instanceof Error ? err.message : 'Failed to load receipt');
    } finally {
      setReceiptLoading(false);
    }
  }, [
    debateStatus,
    firstDebateId,
    firstReceiptId,
    setFirstReceiptId,
    updateProgress,
    _pollReceiptById,
    _pollReceiptIdForDebate,
  ]);

  // Auto-fetch receipt after debate completion (receipt generation can lag slightly).
  useEffect(() => {
    if (debateStatus !== 'completed' || !firstDebateId) return;
    if (receiptLoading || receipt || receiptError) return;
    fetchReceipt();
  }, [debateStatus, firstDebateId, fetchReceipt, receipt, receiptError, receiptLoading]);

  const downloadReceiptExport = useCallback(
    async (format: 'md' | 'pdf') => {
      if (!firstReceiptId) {
        setReceiptError('Receipt is not ready yet');
        return;
      }

      setReceiptError(null);

      const response = await fetch(
        `${apiBase}/api/v2/receipts/${encodeURIComponent(firstReceiptId)}/export?format=${format}&raw=true`,
      );
      if (!response.ok) {
        throw new Error(`Export failed (HTTP ${response.status})`);
      }

      const blob = await response.blob();
      const contentType = response.headers.get('content-type') || '';
      const pdfFallback = format === 'pdf' && contentType.includes('text/html');
      const ext = format === 'md' ? 'md' : pdfFallback ? 'html' : 'pdf';

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `decision-receipt-${firstReceiptId}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },
    [apiBase, firstReceiptId],
  );

  const handleStartDebate = useCallback(async () => {
    if (!firstDebateTopic.trim()) {
      setLocalError('Please enter a topic for your debate');
      return;
    }

    setLocalError(null);
    setReceipt(null);
    setReceiptError(null);
    setReceiptLoading(false);
    setFirstReceiptId(null);
    updateProgress({
      receiptViewed: false,
      firstDebateCompleted: false,
      firstDebateStarted: false,
    });
    setDebateStatus('creating');
    setDebateError(null);

    try {
      // Create the debate via API with receipt generation enabled
      const response = await fetch(`${apiBase}/api/debates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: firstDebateTopic,
          agents: 'anthropic-api,openai-api', // Express: 2 agents (CSV format)
          rounds: selectedTemplate?.rounds || 2,
          enable_receipt_generation: true, // Enable for onboarding
          receipt_min_confidence: 0.5,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || 'Failed to create debate');
      }

      const data = await response.json();
      setFirstDebateId(data.debate_id);
      if (data.receipt_id) {
        setFirstReceiptId(data.receipt_id);
      }
      setDebateStatus('running');
      updateProgress({ firstDebateStarted: true });
    } catch (err) {
      setDebateError(err instanceof Error ? err.message : 'Failed to start debate');
      setDebateStatus('error');
    }
  }, [
    apiBase,
    firstDebateTopic,
    selectedTemplate,
    setFirstDebateId,
    setFirstReceiptId,
    setDebateStatus,
    setDebateError,
    updateProgress,
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">Run Your First Debate</h3>
        <p className="text-sm text-text-muted">Enter a topic to see Aragora in action</p>
      </div>

      {/* Topic Input */}
      <div>
        <label className="block text-sm font-theme-data text-text mb-2">
          What decision do you need to make?
        </label>
        <textarea
          value={firstDebateTopic}
          onChange={(e) => {
            setFirstDebateTopic(e.target.value);
            setLocalError(null);
          }}
          placeholder="e.g., Should we use microservices or a monolith?"
          rows={3}
          disabled={debateStatus === 'running' || debateStatus === 'completed'}
          className="w-full px-4 py-2 bg-bg border border-[var(--accent)]/30 rounded text-text font-theme-data focus:border-[var(--accent)] focus:outline-none disabled:opacity-50"
        />
        {(localError || debateError) && (
          <p className="text-xs text-accent-red mt-1">{localError || debateError}</p>
        )}
      </div>

      {/* Example Topics */}
      {/* Debate Status */}
      {debateStatus === 'creating' && (
        <div className="text-center py-4">
          <div className="text-[var(--accent)] font-theme-data text-sm animate-pulse">
            Creating debate...
          </div>
        </div>
      )}

      {debateStatus === 'running' && (
        <div className="p-4 border border-[var(--acid-cyan)]/30 rounded-lg bg-[var(--acid-cyan)]/5">
          <div className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
            Debate in progress... {wsMessages.length > 0 && `(${wsMessages.length} messages)`}
          </div>
          <div className="text-xs text-text-muted">
            AI agents are debating your topic. Express debates take ~2 minutes.
          </div>
          {/* Show latest message preview */}
          {wsMessages.length > 0 && (
            <div className="mt-2 text-xs text-[var(--acid-cyan)]/70 italic truncate">
              &quot;{wsMessages[wsMessages.length - 1]?.content?.slice(0, 100)}...&quot;
            </div>
          )}
          <div className="mt-3 w-full h-1 bg-[var(--acid-cyan)]/20 rounded-full overflow-hidden">
            <div className="h-full bg-[var(--acid-cyan)] animate-progress-indeterminate" />
          </div>
        </div>
      )}

      {debateStatus === 'completed' && (
        <div className="p-4 border border-[var(--accent)]/30 rounded-lg bg-[var(--accent)]/5">
          <div className="text-sm font-theme-data text-[var(--accent)] mb-2">Debate completed</div>
          <div className="text-xs text-text-muted">
            {receiptLoading && <>Generating your decision receipt...</>}
            {!receiptLoading && receipt && <>Decision receipt ready.</>}
            {!receiptLoading && !receipt && !receiptError && <>Preparing receipt...</>}
            {!receiptLoading && receiptError && <>Receipt not available yet.</>}
          </div>

          {/* Receipt panel */}
          <div className="mt-3 space-y-3">
            {receiptError && <div className="text-xs text-accent-red">{receiptError}</div>}

            {receiptLoading && (
              <div className="w-full h-1 bg-[var(--accent)]/20 rounded-full overflow-hidden">
                <div className="h-full bg-[var(--accent)] animate-progress-indeterminate" />
              </div>
            )}

            {receipt && (
              <div className="border border-[var(--accent)]/20 rounded bg-surface/40 p-3">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="text-xs font-theme-data text-text-muted">DECISION RECEIPT</div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 text-[10px] font-theme-data rounded border border-[var(--accent)]/30 text-[var(--accent)] bg-[var(--accent)]/10">
                      {(receipt.verdict || 'NEEDS_REVIEW').toString().toUpperCase()}
                    </span>
                    <span className="text-[10px] font-theme-data text-text-muted">
                      {typeof receipt.confidence === 'number'
                        ? `${Math.round(receipt.confidence * 100)}%`
                        : '...'}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs text-text">
                  <div>
                    <div className="text-[10px] text-text-muted font-theme-data">Receipt ID</div>
                    <div className="font-theme-data break-all">
                      {firstReceiptId || receipt.receipt_id || '...'}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-text-muted font-theme-data">Risk</div>
                    <div className="font-theme-data">
                      {(receipt.risk_level || 'MEDIUM').toString().toUpperCase()}
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={() =>
                      downloadReceiptExport('md').catch((e) =>
                        setReceiptError(e instanceof Error ? e.message : 'Export failed'),
                      )
                    }
                    className="px-3 py-1.5 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    DOWNLOAD MD
                  </button>
                  <button
                    onClick={() =>
                      downloadReceiptExport('pdf').catch((e) =>
                        setReceiptError(e instanceof Error ? e.message : 'Export failed'),
                      )
                    }
                    className="px-3 py-1.5 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                  >
                    DOWNLOAD PDF
                  </button>
                  {firstReceiptId && (
                    <a
                      href={`${apiBase}/api/v2/receipts/${encodeURIComponent(firstReceiptId)}/export?format=html&raw=true`}
                      target="_blank"
                      rel="noreferrer"
                      className="px-3 py-1.5 text-xs font-theme-data border border-border text-text-muted hover:border-[var(--accent)]/40 hover:text-text transition-colors"
                    >
                      OPEN HTML
                    </a>
                  )}
                </div>
              </div>
            )}

            {!receiptLoading && !receipt && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() =>
                    fetchReceipt().catch((err) => {
                      console.warn('[FirstDebateStep] Retry receipt fetch failed:', err);
                      setReceiptError(
                        err instanceof Error ? err.message : 'Failed to load receipt',
                      );
                    })
                  }
                  className="px-3 py-1.5 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                >
                  RETRY RECEIPT
                </button>
                <button
                  onClick={() => updateProgress({ receiptViewed: true })}
                  className="px-3 py-1.5 text-xs font-theme-data border border-border text-text-muted hover:border-[var(--acid-cyan)]/40 hover:text-text transition-colors"
                >
                  CONTINUE WITHOUT RECEIPT
                </button>
              </div>
            )}

            {firstDebateId && (
              <div className="text-[10px] text-text-muted font-theme-data">
                Debate ID: {firstDebateId}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Start Button */}
      {debateStatus === 'idle' && (
        <button
          onClick={handleStartDebate}
          disabled={!firstDebateTopic.trim()}
          className="w-full px-4 py-3 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          START DEBATE
        </button>
      )}

      {/* Template Info */}
      {selectedTemplate && debateStatus === 'idle' && (
        <div className="text-center text-xs text-text-muted">
          Using template: {selectedTemplate.name} ({selectedTemplate.agentsCount} agents,{' '}
          {selectedTemplate.rounds} rounds)
        </div>
      )}
    </div>
  );
}
