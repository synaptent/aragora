'use client';

import { useState, useEffect, useCallback } from 'react';
import { useDebateInterventions } from '@/hooks/useDebateInterventions';
import type { InterventionEntry } from '@/hooks/useDebateInterventions';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface TextInputModalProps {
  title: string;
  placeholder: string;
  fieldName: string;
  /** Optional second field (e.g. target_agent for nudge, source for evidence) */
  secondaryField?: { label: string; placeholder: string };
  onSubmit: (text: string, secondary?: string) => void;
  onClose: () => void;
}

function TextInputModal({
  title,
  placeholder,
  fieldName,
  secondaryField,
  onSubmit,
  onClose,
}: TextInputModalProps) {
  const [text, setText] = useState('');
  const [secondary, setSecondary] = useState('');

  const handleSubmit = () => {
    if (!text.trim()) return;
    onSubmit(text.trim(), secondary.trim() || undefined);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl p-6 w-full max-w-md mx-4">
        <h3 className="text-lg font-semibold mb-4">{title}</h3>

        <label className="block text-sm font-medium mb-1">{fieldName}</label>
        <textarea
          className="w-full border rounded-lg p-2 text-sm mb-3 resize-none dark:bg-zinc-800 dark:border-zinc-700"
          rows={4}
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />

        {secondaryField && (
          <>
            <label className="block text-sm font-medium mb-1">{secondaryField.label}</label>
            <input
              type="text"
              className="w-full border rounded-lg p-2 text-sm mb-3 dark:bg-zinc-800 dark:border-zinc-700"
              placeholder={secondaryField.placeholder}
              value={secondary}
              onChange={(e) => setSecondary(e.target.value)}
            />
          </>
        )}

        <div className="flex justify-end gap-2 mt-2">
          <button
            className="px-4 py-2 text-sm rounded-lg bg-zinc-200 dark:bg-zinc-700 hover:bg-zinc-300 dark:hover:bg-zinc-600"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={!text.trim()}
            onClick={handleSubmit}
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function InterventionLogEntry({ entry }: { entry: InterventionEntry }) {
  const typeColors: Record<string, string> = {
    pause: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
    resume: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    nudge: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    challenge: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    inject_evidence: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  };

  return (
    <div className="flex items-start gap-2 py-2 border-b border-zinc-100 dark:border-zinc-800 last:border-b-0">
      <span
        className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${typeColors[entry.type] || 'bg-zinc-100 text-zinc-700'}`}
      >
        {entry.type}
      </span>
      <div className="flex-1 min-w-0">
        {entry.message && (
          <p className="text-sm text-zinc-700 dark:text-zinc-300 truncate">{entry.message}</p>
        )}
        {entry.target_agent && (
          <p className="text-xs text-zinc-500">Target: {entry.target_agent}</p>
        )}
        {entry.source && <p className="text-xs text-zinc-500">Source: {entry.source}</p>}
      </div>
      <span className="text-xs text-zinc-400 whitespace-nowrap">
        {formatTimestamp(entry.timestamp)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

type ModalType = 'nudge' | 'challenge' | 'evidence' | null;

interface InterventionPanelProps {
  debateId: string;
  /** If true, all controls are disabled (e.g. debate is complete) */
  disabled?: boolean;
  /** Callback when the debate state changes */
  onStateChange?: (state: string) => void;
  /** Auto-refresh interval for the log in ms (0 to disable, default 5000) */
  refreshInterval?: number;
}

/**
 * Floating intervention panel for live debate control.
 *
 * Displays pause/resume buttons, action buttons that open modals
 * for nudge/challenge/evidence input, and an intervention history log.
 */
export function InterventionPanel({
  debateId,
  disabled = false,
  onStateChange,
  refreshInterval = 5000,
}: InterventionPanelProps) {
  const {
    loading,
    error,
    log,
    debateState,
    pause,
    resume,
    nudge,
    challenge,
    injectEvidence,
    refreshLog,
  } = useDebateInterventions(debateId);

  const [activeModal, setActiveModal] = useState<ModalType>(null);
  const [collapsed, setCollapsed] = useState(false);

  // Notify parent of state changes
  useEffect(() => {
    if (debateState && onStateChange) {
      onStateChange(debateState);
    }
  }, [debateState, onStateChange]);

  // Auto-refresh log
  useEffect(() => {
    if (refreshInterval <= 0 || disabled) return;
    refreshLog();
    const interval = setInterval(refreshLog, refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval, disabled, refreshLog]);

  const isPaused = debateState === 'paused';
  const isCompleted = debateState === 'completed';
  const allDisabled = disabled || isCompleted || loading;

  const handleNudge = useCallback(
    (message: string, targetAgent?: string) => {
      nudge(message, targetAgent);
    },
    [nudge],
  );

  const handleChallenge = useCallback(
    (challengeText: string) => {
      challenge(challengeText);
    },
    [challenge],
  );

  const handleEvidence = useCallback(
    (evidence: string, source?: string) => {
      injectEvidence(evidence, source);
    },
    [injectEvidence],
  );

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="fixed bottom-4 right-4 z-40 bg-blue-600 text-white px-4 py-2 rounded-full shadow-lg hover:bg-blue-700 text-sm font-medium"
        title="Show intervention controls"
      >
        Interventions
      </button>
    );
  }

  return (
    <>
      <div className="fixed bottom-4 right-4 z-40 w-80 bg-white dark:bg-zinc-900 rounded-xl shadow-2xl border border-zinc-200 dark:border-zinc-700 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-zinc-50 dark:bg-zinc-800 border-b border-zinc-200 dark:border-zinc-700">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-sm">Interventions</h3>
            {debateState && (
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  isPaused
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200'
                    : isCompleted
                      ? 'bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-400'
                      : 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                }`}
              >
                {debateState}
              </span>
            )}
          </div>
          <button
            onClick={() => setCollapsed(true)}
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 text-sm"
            title="Collapse panel"
          >
            x
          </button>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 text-xs">
            {error}
          </div>
        )}

        {/* Controls */}
        <div className="px-4 py-3 space-y-2">
          {/* Pause / Resume */}
          <div className="flex gap-2">
            <button
              onClick={isPaused ? resume : pause}
              disabled={allDisabled}
              className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                isPaused
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-amber-500 text-white hover:bg-amber-600'
              }`}
            >
              {isPaused ? 'Resume' : 'Pause'}
            </button>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              onClick={() => setActiveModal('nudge')}
              disabled={allDisabled}
              className="flex-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Nudge
            </button>
            <button
              onClick={() => setActiveModal('challenge')}
              disabled={allDisabled}
              className="flex-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-red-50 text-red-700 hover:bg-red-100 dark:bg-red-900/30 dark:text-red-300 dark:hover:bg-red-900/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Challenge
            </button>
            <button
              onClick={() => setActiveModal('evidence')}
              disabled={allDisabled}
              className="flex-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 dark:bg-purple-900/30 dark:text-purple-300 dark:hover:bg-purple-900/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Evidence
            </button>
          </div>
        </div>

        {/* Intervention log */}
        <div className="border-t border-zinc-200 dark:border-zinc-700">
          <div className="px-4 py-2 bg-zinc-50 dark:bg-zinc-800">
            <span className="text-xs font-medium text-zinc-500">
              History ({log?.entry_count ?? 0})
            </span>
          </div>
          <div className="max-h-48 overflow-y-auto px-4 py-1">
            {log && log.entries.length > 0 ? (
              [...log.entries]
                .reverse()
                .map((entry, idx) => <InterventionLogEntry key={idx} entry={entry} />)
            ) : (
              <p className="text-xs text-zinc-400 py-2 text-center">No interventions yet</p>
            )}
          </div>
        </div>
      </div>

      {/* Modals */}
      {activeModal === 'nudge' && (
        <TextInputModal
          title="Send Nudge"
          fieldName="Message"
          placeholder="Consider the economic implications..."
          secondaryField={{ label: 'Target Agent (optional)', placeholder: 'e.g. claude, gpt4' }}
          onSubmit={handleNudge}
          onClose={() => setActiveModal(null)}
        />
      )}

      {activeModal === 'challenge' && (
        <TextInputModal
          title="Inject Challenge"
          fieldName="Challenge"
          placeholder="What about the counterargument that..."
          onSubmit={handleChallenge}
          onClose={() => setActiveModal(null)}
        />
      )}

      {activeModal === 'evidence' && (
        <TextInputModal
          title="Inject Evidence"
          fieldName="Evidence"
          placeholder="According to recent research..."
          secondaryField={{ label: 'Source (optional)', placeholder: 'e.g. https://arxiv.org/...' }}
          onSubmit={handleEvidence}
          onClose={() => setActiveModal(null)}
        />
      )}
    </>
  );
}

export default InterventionPanel;
