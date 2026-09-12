'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  useBatchDebate,
  type BatchItem,
  type BatchStatusValue,
  type BatchItemStatus,
} from '@/hooks/useBatchDebate';

// ============================================================================
// Status Badge Component
// ============================================================================

const STATUS_COLORS: Record<BatchStatusValue, { text: string; bg: string }> = {
  pending: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/10' },
  processing: { text: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/10' },
  completed: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/10' },
  failed: { text: 'text-acid-red', bg: 'bg-acid-red/10' },
  cancelled: { text: 'text-text-muted', bg: 'bg-surface' },
};

function StatusBadge({ status }: { status: BatchStatusValue }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.pending;
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data uppercase ${colors.text} ${colors.bg} rounded`}
    >
      {status}
    </span>
  );
}

// ============================================================================
// Progress Bar Component
// ============================================================================

function ProgressBar({ progress, status }: { progress: number; status: BatchStatusValue }) {
  const getColor = () => {
    if (status === 'failed') return 'bg-acid-red';
    if (status === 'completed') return 'bg-[var(--accent)]';
    if (status === 'processing') return 'bg-[var(--acid-cyan)]';
    return 'bg-acid-yellow';
  };

  return (
    <div className="w-full h-2 bg-surface rounded overflow-hidden">
      <div
        className={`h-full ${getColor()} transition-all duration-300`}
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}

// ============================================================================
// Batch Submit Form
// ============================================================================

interface BatchSubmitFormProps {
  onSubmit: (items: BatchItem[], webhookUrl?: string) => Promise<void>;
  submitting: boolean;
  error: string | null;
}

function BatchSubmitForm({ onSubmit, submitting, error }: BatchSubmitFormProps) {
  const [inputMode, setInputMode] = useState<'text' | 'json'>('text');
  const [textInput, setTextInput] = useState('');
  const [jsonInput, setJsonInput] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setParseError(null);

      let items: BatchItem[] = [];

      if (inputMode === 'text') {
        // Parse text input - one question per line
        const lines = textInput.split('\n').filter((l) => l.trim());
        if (lines.length === 0) {
          setParseError('Enter at least one question');
          return;
        }
        items = lines.map((question) => ({ question: question.trim() }));
      } else {
        // Parse JSON input
        try {
          const parsed = JSON.parse(jsonInput);
          if (Array.isArray(parsed)) {
            items = parsed.map((item) => (typeof item === 'string' ? { question: item } : item));
          } else if (parsed.items && Array.isArray(parsed.items)) {
            items = parsed.items;
          } else {
            setParseError('JSON must be an array of items or { items: [...] }');
            return;
          }
        } catch {
          setParseError('Invalid JSON format');
          return;
        }
      }

      if (items.length === 0) {
        setParseError('No valid items to submit');
        return;
      }

      if (items.length > 1000) {
        setParseError('Maximum 1000 items per batch');
        return;
      }

      await onSubmit(items, webhookUrl || undefined);
    },
    [inputMode, textInput, jsonInput, webhookUrl, onSubmit],
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Input Mode Toggle */}
      <div className="flex gap-2" role="group" aria-label="Input format selection">
        <button
          type="button"
          onClick={() => setInputMode('text')}
          aria-pressed={inputMode === 'text'}
          className={`px-3 py-1 text-xs font-theme-data border ${
            inputMode === 'text'
              ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
              : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
          }`}
        >
          TEXT
        </button>
        <button
          type="button"
          onClick={() => setInputMode('json')}
          aria-pressed={inputMode === 'json'}
          className={`px-3 py-1 text-xs font-theme-data border ${
            inputMode === 'json'
              ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
              : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
          }`}
        >
          JSON
        </button>
      </div>

      {/* Input Area */}
      {inputMode === 'text' ? (
        <div>
          <label
            htmlFor="batch-questions-input"
            className="block text-xs font-theme-data text-text-muted mb-1"
          >
            Questions (one per line)
          </label>
          <textarea
            id="batch-questions-input"
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            rows={8}
            placeholder="What is the best programming language for beginners?&#10;Should we use microservices or monolith?&#10;Is AI going to replace programmers?"
            className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none resize-none"
          />
        </div>
      ) : (
        <div>
          <label
            htmlFor="batch-json-input"
            className="block text-xs font-theme-data text-text-muted mb-1"
          >
            JSON Items
          </label>
          <textarea
            id="batch-json-input"
            value={jsonInput}
            onChange={(e) => setJsonInput(e.target.value)}
            rows={8}
            placeholder='[&#10;  { "question": "What is AI?", "agents": "claude,gpt-4o", "rounds": 3 },&#10;  { "question": "Is Rust better than Go?" }&#10;]'
            className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none resize-none"
          />
        </div>
      )}

      {/* Webhook URL (collapsed by default) */}
      <details className="group">
        <summary className="text-xs font-theme-data text-text-muted cursor-pointer hover:text-[var(--accent)]">
          <span aria-hidden="true">[+]</span> Webhook Configuration
        </summary>
        <div className="mt-2">
          <label
            htmlFor="batch-webhook-url"
            className="block text-xs font-theme-data text-text-muted mb-1"
          >
            Webhook URL (optional)
          </label>
          <input
            id="batch-webhook-url"
            type="url"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://your-server.com/webhook"
            className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
          />
          <p id="batch-webhook-help" className="mt-1 text-xs font-theme-data text-text-muted">
            Receive POST notifications when batch completes
          </p>
        </div>
      </details>

      {/* Error Display */}
      {(parseError || error) && (
        <div className="p-3 text-xs font-theme-data text-acid-red bg-acid-red/10 border border-acid-red/30">
          {'>'} {parseError || error}
        </div>
      )}

      {/* Submit Button */}
      <button
        type="submit"
        disabled={submitting}
        className="w-full py-2 bg-[var(--accent)]/10 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {submitting ? 'SUBMITTING...' : 'SUBMIT BATCH'}
      </button>
    </form>
  );
}

// ============================================================================
// Batch Status Card
// ============================================================================

interface BatchStatusCardProps {
  batchId: string;
  status: BatchStatusValue;
  totalItems: number;
  completedItems: number;
  failedItems: number;
  progress: number;
  createdAt: string;
  onRefresh: () => void;
  onClear: () => void;
  isPolling: boolean;
}

function BatchStatusCard({
  batchId,
  status,
  totalItems,
  completedItems,
  failedItems,
  progress,
  createdAt,
  onRefresh,
  onClear,
  isPolling,
}: BatchStatusCardProps) {
  return (
    <div className="p-4 bg-surface border border-[var(--accent)]/30">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-theme-data text-[var(--accent)]">BATCH</span>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center gap-2">
          {isPolling && (
            <span className="text-xs font-theme-data text-[var(--acid-cyan)] animate-pulse">
              POLLING
            </span>
          )}
          <button
            onClick={onRefresh}
            className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
          >
            [REFRESH]
          </button>
          <button
            onClick={onClear}
            className="text-xs font-theme-data text-text-muted hover:text-acid-red"
          >
            [CLEAR]
          </button>
        </div>
      </div>

      <div className="mb-3">
        <code className="text-xs font-theme-data text-text-muted">{batchId}</code>
      </div>

      <ProgressBar progress={progress} status={status} />

      <div className="mt-3 grid grid-cols-3 gap-4 text-center">
        <div>
          <div className="text-lg font-theme-data text-[var(--accent)]">{completedItems}</div>
          <div className="text-xs font-theme-data text-text-muted">COMPLETED</div>
        </div>
        <div>
          <div className="text-lg font-theme-data text-acid-red">{failedItems}</div>
          <div className="text-xs font-theme-data text-text-muted">FAILED</div>
        </div>
        <div>
          <div className="text-lg font-theme-data text-text">{totalItems}</div>
          <div className="text-xs font-theme-data text-text-muted">TOTAL</div>
        </div>
      </div>

      <div className="mt-3 text-xs font-theme-data text-text-muted">
        Started: {new Date(createdAt).toLocaleString()}
      </div>
    </div>
  );
}

// ============================================================================
// Batch Results Table
// ============================================================================

interface BatchResultsTableProps {
  items: BatchItemStatus[];
}

function BatchResultsTable({ items }: BatchResultsTableProps) {
  if (items.length === 0) {
    return (
      <div className="p-4 text-center text-xs font-theme-data text-text-muted">
        No items to display
      </div>
    );
  }

  return (
    <div className="overflow-x-auto max-h-96 overflow-y-auto">
      <table className="w-full text-xs font-theme-data">
        <thead className="sticky top-0 bg-bg">
          <tr className="border-b border-[var(--accent)]/20">
            <th className="py-2 px-3 text-left text-text-muted">#</th>
            <th className="py-2 px-3 text-left text-text-muted">QUESTION</th>
            <th className="py-2 px-3 text-left text-text-muted">STATUS</th>
            <th className="py-2 px-3 text-left text-text-muted">RESULT</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={idx} className="border-b border-[var(--accent)]/10 hover:bg-surface/50">
              <td className="py-2 px-3 text-text-muted">{item.index + 1}</td>
              <td className="py-2 px-3 text-text max-w-xs truncate" title={item.question}>
                {item.question}
              </td>
              <td className="py-2 px-3">
                <StatusBadge status={item.status} />
              </td>
              <td className="py-2 px-3">
                {item.debate_id ? (
                  <Link
                    href={`/debate/${item.debate_id}`}
                    className="text-[var(--acid-cyan)] hover:underline"
                  >
                    [VIEW]
                  </Link>
                ) : item.error ? (
                  <span className="text-acid-red" title={item.error}>
                    {item.error.slice(0, 30)}...
                  </span>
                ) : (
                  <span className="text-text-muted">-</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================================
// Batch History List
// ============================================================================

interface BatchHistoryListProps {
  onSelectBatch: (batchId: string) => void;
}

function BatchHistoryList({ onSelectBatch }: BatchHistoryListProps) {
  const { batches, batchesLoading, batchesError, listBatches } = useBatchDebate();
  const [statusFilter, setStatusFilter] = useState<BatchStatusValue | ''>('');

  useEffect(() => {
    listBatches(50, statusFilter || undefined);
  }, [listBatches, statusFilter]);

  return (
    <div>
      {/* Filter */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-theme-data text-text-muted">FILTER:</span>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as BatchStatusValue | '')}
          className="px-2 py-1 text-xs font-theme-data bg-bg border border-[var(--accent)]/30 text-text focus:outline-none"
        >
          <option value="">ALL</option>
          <option value="pending">PENDING</option>
          <option value="processing">PROCESSING</option>
          <option value="completed">COMPLETED</option>
          <option value="failed">FAILED</option>
        </select>
        <button
          onClick={() => listBatches(50, statusFilter || undefined)}
          className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
        >
          [REFRESH]
        </button>
      </div>

      {/* Loading/Error */}
      {batchesLoading && (
        <div className="p-4 text-xs font-theme-data text-text-muted animate-pulse">
          Loading batches...
        </div>
      )}
      {batchesError && (
        <div className="p-3 text-xs font-theme-data text-acid-red bg-acid-red/10 border border-acid-red/30">
          {batchesError}
        </div>
      )}

      {/* Batch List */}
      {!batchesLoading && batches.length === 0 && (
        <div className="p-4 text-center text-xs font-theme-data text-text-muted">
          No batches found
        </div>
      )}
      {batches.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {batches.map((batch) => (
            <button
              key={batch.batch_id}
              onClick={() => onSelectBatch(batch.batch_id)}
              className="w-full p-3 text-left bg-surface hover:bg-surface/80 border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors"
            >
              <div className="flex items-center justify-between">
                <code className="text-xs font-theme-data text-text-muted truncate max-w-[180px]">
                  {batch.batch_id}
                </code>
                <StatusBadge status={batch.status} />
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs font-theme-data text-text-muted">
                <span>
                  {batch.completed_items}/{batch.total_items} done
                </span>
                {batch.failed_items > 0 && (
                  <span className="text-acid-red">{batch.failed_items} failed</span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Queue Status Display
// ============================================================================

function QueueStatusDisplay() {
  const { queueStatus, queueLoading, getQueueStatus } = useBatchDebate();

  useEffect(() => {
    getQueueStatus();
  }, [getQueueStatus]);

  if (queueLoading) {
    return <div className="text-xs font-theme-data text-text-muted">Loading queue status...</div>;
  }

  if (!queueStatus) {
    return null;
  }

  return (
    <div className="p-3 bg-surface/50 border border-[var(--accent)]/20">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-theme-data text-[var(--accent)]">QUEUE STATUS</span>
        <span
          className={`text-xs font-theme-data ${queueStatus.active ? 'text-[var(--accent)]' : 'text-acid-red'}`}
        >
          {queueStatus.active ? 'ACTIVE' : 'INACTIVE'}
        </span>
      </div>
      {queueStatus.active && (
        <div className="grid grid-cols-3 gap-2 text-xs font-theme-data">
          <div>
            <span className="text-text-muted">Active: </span>
            <span className="text-[var(--acid-cyan)]">{queueStatus.active_count || 0}</span>
          </div>
          <div>
            <span className="text-text-muted">Max: </span>
            <span className="text-text">{queueStatus.max_concurrent || '-'}</span>
          </div>
          <div>
            <span className="text-text-muted">Total: </span>
            <span className="text-text">{queueStatus.total_batches || 0}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Panel Component
// ============================================================================

export function BatchDebatePanel() {
  const batch = useBatchDebate();
  const [activeTab, setActiveTab] = useState<'submit' | 'status' | 'history'>('submit');

  const handleSubmit = useCallback(
    async (items: BatchItem[], webhookUrl?: string) => {
      const result = await batch.submitBatch({ items, webhook_url: webhookUrl });
      if (result) {
        setActiveTab('status');
        batch.pollBatchStatus(result.batch_id);
      }
    },
    [batch],
  );

  const handleSelectBatch = useCallback(
    (batchId: string) => {
      batch.pollBatchStatus(batchId);
      setActiveTab('status');
    },
    [batch],
  );

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} BATCH DEBATES
        </span>
      </div>

      {/* Queue Status */}
      <div className="px-4 py-2 border-b border-[var(--accent)]/10">
        <QueueStatusDisplay />
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--accent)]/10">
        {(['submit', 'status', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 px-4 py-2 text-xs font-theme-data uppercase transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {activeTab === 'submit' && (
          <BatchSubmitForm
            onSubmit={handleSubmit}
            submitting={batch.submitting}
            error={batch.submitError}
          />
        )}

        {activeTab === 'status' && (
          <div className="space-y-4">
            {batch.currentBatch ? (
              <>
                <BatchStatusCard
                  batchId={batch.currentBatch.batch_id}
                  status={batch.currentBatch.status}
                  totalItems={batch.currentBatch.total_items}
                  completedItems={batch.currentBatch.completed_items}
                  failedItems={batch.currentBatch.failed_items}
                  progress={batch.progress}
                  createdAt={batch.currentBatch.created_at}
                  onRefresh={() => batch.getBatchStatus(batch.currentBatch!.batch_id)}
                  onClear={batch.clearBatch}
                  isPolling={batch.isPolling}
                />
                <div className="border border-[var(--accent)]/20">
                  <div className="px-3 py-2 border-b border-[var(--accent)]/10 bg-bg/50">
                    <span className="text-xs font-theme-data text-text-muted">ITEMS</span>
                  </div>
                  <BatchResultsTable items={batch.currentBatch.items || []} />
                </div>
              </>
            ) : batch.batchLoading ? (
              <div className="p-8 text-center text-xs font-theme-data text-text-muted animate-pulse">
                Loading batch status...
              </div>
            ) : batch.batchError ? (
              <div className="p-4 text-center">
                <div className="text-xs font-theme-data text-acid-red mb-2">{batch.batchError}</div>
                <button
                  onClick={() => setActiveTab('submit')}
                  className="text-xs font-theme-data text-[var(--acid-cyan)] hover:underline"
                >
                  [SUBMIT NEW BATCH]
                </button>
              </div>
            ) : (
              <div className="p-8 text-center">
                <div className="text-xs font-theme-data text-text-muted mb-2">
                  No batch selected
                </div>
                <button
                  onClick={() => setActiveTab('submit')}
                  className="text-xs font-theme-data text-[var(--acid-cyan)] hover:underline"
                >
                  [SUBMIT NEW BATCH]
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === 'history' && <BatchHistoryList onSelectBatch={handleSelectBatch} />}
      </div>
    </div>
  );
}
