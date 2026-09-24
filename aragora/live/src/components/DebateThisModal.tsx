'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';

export interface DebateThisModalProps {
  question: string;
  context?: string;
  source?: string;
  onClose: () => void;
}

type DebateFormat = 'quick' | 'thorough';

const SOURCE_LABELS: Record<string, string> = {
  pulse: 'Trending Topic',
  receipt: 'Decision Receipt',
  pipeline: 'Pipeline Gate',
  dashboard: 'Dashboard',
  debate_this: 'Quick Launch',
};

export function DebateThisModal({
  question: initialQuestion,
  context,
  source,
  onClose,
}: DebateThisModalProps) {
  const router = useRouter();
  const [question, setQuestion] = useState(initialQuestion);
  const [format, setFormat] = useState<DebateFormat>('quick');
  const [showContext, setShowContext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStart = useCallback(async () => {
    if (!question.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || '';
      const res = await fetch(`${apiBase}/api/v1/debates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: question.trim(),
          context,
          rounds: format === 'quick' ? 4 : 9,
          auto_select: true,
          metadata: { source: source || 'debate_this' },
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || `Request failed (${res.status})`);
        return;
      }

      const debateId = data.debate_id || data.id;
      if (debateId) {
        onClose();
        router.push(`/debates/${debateId}`);
      } else {
        setError('No debate ID returned');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start debate');
    } finally {
      setLoading(false);
    }
  }, [question, format, context, source, router, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-lg mx-4 bg-surface border border-[var(--accent)]/30 rounded-lg shadow-2xl shadow-acid-green/5">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <span className="text-[var(--accent)] font-theme-data text-sm font-bold">
              DEBATE THIS
            </span>
            {source && (
              <span className="px-2 py-0.5 text-[10px] font-theme-data text-text-muted border border-border rounded">
                {SOURCE_LABELS[source] || source}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center text-text-muted hover:text-[var(--accent)] transition-colors"
            aria-label="Close"
          >
            x
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Question */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1.5">QUESTION</label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none resize-none"
              placeholder="What should be debated?"
            />
          </div>

          {/* Format toggle */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1.5">FORMAT</label>
            <div className="flex gap-2">
              <button
                onClick={() => setFormat('quick')}
                className={`flex-1 px-3 py-2 text-xs font-theme-data rounded border transition-all ${
                  format === 'quick'
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'bg-bg border-border text-text-muted hover:border-text-muted'
                }`}
              >
                <div className="font-bold">QUICK</div>
                <div className="text-[10px] mt-0.5 opacity-70">4 rounds</div>
              </button>
              <button
                onClick={() => setFormat('thorough')}
                className={`flex-1 px-3 py-2 text-xs font-theme-data rounded border transition-all ${
                  format === 'thorough'
                    ? 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)] text-[var(--acid-cyan)]'
                    : 'bg-bg border-border text-text-muted hover:border-text-muted'
                }`}
              >
                <div className="font-bold">THOROUGH</div>
                <div className="text-[10px] mt-0.5 opacity-70">9 rounds</div>
              </button>
            </div>
          </div>

          {/* Context preview (collapsible) */}
          {context && (
            <div>
              <button
                onClick={() => setShowContext(!showContext)}
                className="flex items-center gap-1 text-xs font-theme-data text-text-muted hover:text-[var(--acid-cyan)] transition-colors"
              >
                <span>{showContext ? 'v' : '>'}</span>
                <span>Context ({context.length} chars)</span>
              </button>
              {showContext && (
                <div className="mt-2 px-3 py-2 bg-bg border border-border rounded text-xs font-theme-data text-text-muted max-h-32 overflow-y-auto">
                  {context}
                </div>
              )}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-xs font-theme-data text-red-400">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-border">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-theme-data text-text-muted hover:text-text border border-border rounded transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleStart}
            disabled={loading || !question.trim()}
            className="px-4 py-2 text-xs font-theme-data font-bold bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Starting...' : 'Start Debate'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default DebateThisModal;
