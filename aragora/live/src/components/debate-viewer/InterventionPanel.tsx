'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';
import { getAgentColors } from '@/utils/agentColors';

interface InterventionPanelProps {
  debateId: string;
  isActive: boolean;
  isPaused: boolean;
  currentRound: number;
  totalRounds: number;
  agents: string[];
  consensusThreshold: number;
  onPause?: () => void;
  onResume?: () => void;
  onInject?: (content: string) => void;
  onWeightChange?: (agent: string, weight: number) => void;
  onThresholdChange?: (threshold: number) => void;
  apiBase?: string;
}

interface AgentWeight {
  agent: string;
  weight: number;
}

type InterventionStatus = 'applied' | 'pending' | 'failed';

interface InterventionRecord {
  id: string;
  type:
    | 'argument'
    | 'follow_up'
    | 'nudge'
    | 'challenge'
    | 'weight_change'
    | 'threshold_change'
    | 'pause'
    | 'resume';
  content: string;
  timestamp: number;
  status: InterventionStatus;
}

interface ToastNotification {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}

/** Inline hex colors for the weight bar segments, keyed by agent prefix. */
const AGENT_BAR_COLORS: Record<string, string> = {
  gemini: '#bf00ff',
  codex: '#ffd700',
  gpt: '#ffd700',
  openai: '#ffd700',
  claude: '#00ffff',
  anthropic: '#00ffff',
  grok: '#ff0040',
  xai: '#ff0040',
};

const DEFAULT_BAR_COLOR = '#39ff14'; // acid-green fallback

function getBarColor(agentName: string): string {
  const name = agentName.toLowerCase();
  for (const [prefix, color] of Object.entries(AGENT_BAR_COLORS)) {
    if (name.startsWith(prefix)) return color;
  }
  return DEFAULT_BAR_COLOR;
}

function getStoredAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem('aragora_tokens');
  if (!stored) return null;
  try {
    return (JSON.parse(stored) as { access_token?: string }).access_token || null;
  } catch {
    return null;
  }
}

function requestHeaders(contentType = true): Record<string, string> {
  const headers: Record<string, string> = {};
  if (contentType) {
    headers['Content-Type'] = 'application/json';
  }
  const token = getStoredAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const TYPE_LABELS: Record<InterventionRecord['type'], string> = {
  argument: 'Evidence Injection',
  follow_up: 'Follow-up Question',
  nudge: 'Direction Nudge',
  challenge: 'Challenge Claim',
  weight_change: 'Weight Change',
  threshold_change: 'Threshold Change',
  pause: 'Debate Paused',
  resume: 'Debate Resumed',
};

const STATUS_STYLES: Record<InterventionStatus, { text: string; bg: string; border: string }> = {
  applied: { text: 'text-green-400', bg: 'bg-green-500/10', border: 'border-green-500/30' },
  pending: { text: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
  failed: { text: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/30' },
};

export function InterventionPanel({
  debateId,
  isActive,
  isPaused,
  currentRound,
  totalRounds,
  agents,
  consensusThreshold: initialThreshold,
  onPause,
  onResume,
  onInject,
  onWeightChange,
  onThresholdChange,
  apiBase = API_BASE_URL,
}: InterventionPanelProps) {
  const debatePath = `${apiBase}/api/v1/debates/${encodeURIComponent(debateId)}`;
  const [injection, setInjection] = useState('');
  const [injecting, setInjecting] = useState(false);
  const [pauseLoading, setPauseLoading] = useState(false);
  const [agentWeights, setAgentWeights] = useState<AgentWeight[]>(
    agents.map((agent) => ({ agent, weight: 1.0 })),
  );
  const [previousWeights, setPreviousWeights] = useState<AgentWeight[] | null>(null);
  const [showWeightComparison, setShowWeightComparison] = useState(false);
  const [consensusThreshold, setConsensusThreshold] = useState(initialThreshold);
  const [followUpQuestion, setFollowUpQuestion] = useState('');
  const [nudgeDirection, setNudgeDirection] = useState('');
  const [challengeClaim, setChallengeClaim] = useState('');
  const [activeTab, setActiveTab] = useState<'inject' | 'nudge' | 'control' | 'weights'>('inject');
  const [toasts, setToasts] = useState<ToastNotification[]>([]);
  const [history, setHistory] = useState<InterventionRecord[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const weightComparisonTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-dismiss toasts
  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts.map((t) =>
      setTimeout(() => {
        setToasts((prev) => prev.filter((toast) => toast.id !== t.id));
      }, 4000),
    );
    return () => timers.forEach(clearTimeout);
  }, [toasts]);

  // Clean up weight comparison timeout on unmount
  useEffect(() => {
    return () => {
      if (weightComparisonTimeout.current) {
        clearTimeout(weightComparisonTimeout.current);
      }
    };
  }, []);

  const showToast = useCallback((message: string, type: ToastNotification['type'] = 'success') => {
    setToasts((prev) => [...prev, { id: generateId(), message, type }]);
  }, []);

  const addToHistory = useCallback(
    (type: InterventionRecord['type'], content: string, status: InterventionStatus = 'applied') => {
      setHistory((prev) => [
        ...prev,
        { id: generateId(), type, content, timestamp: Date.now(), status },
      ]);
    },
    [],
  );

  const updateHistoryStatus = useCallback((id: string, status: InterventionStatus) => {
    setHistory((prev) => prev.map((r) => (r.id === id ? { ...r, status } : r)));
  }, []);

  // Handle pause/resume
  const handlePauseToggle = useCallback(async () => {
    setPauseLoading(true);
    const action = isPaused ? 'resume' : 'pause';
    const recordId = generateId();
    const recordType = isPaused ? 'resume' : 'pause';
    setHistory((prev) => [
      ...prev,
      {
        id: recordId,
        type: recordType as InterventionRecord['type'],
        content: isPaused ? 'Resumed debate' : 'Paused debate',
        timestamp: Date.now(),
        status: 'pending',
      },
    ]);
    try {
      const response = await fetch(`${debatePath}/${action}`, {
        method: 'POST',
        headers: requestHeaders(false),
      });

      if (response.ok) {
        if (isPaused) {
          onResume?.();
          showToast('Debate resumed', 'success');
        } else {
          onPause?.();
          showToast('Debate paused -- agents will hold after current turn', 'info');
        }
        updateHistoryStatus(recordId, 'applied');
      } else {
        showToast(`Failed to ${action} debate`, 'error');
        updateHistoryStatus(recordId, 'failed');
      }
    } catch (error) {
      logger.error('Failed to toggle pause:', error);
      showToast(`Failed to ${action} debate`, 'error');
      updateHistoryStatus(recordId, 'failed');
    } finally {
      setPauseLoading(false);
    }
  }, [debatePath, isPaused, onPause, onResume, showToast, updateHistoryStatus]);

  // Handle argument injection
  const handleInject = useCallback(async () => {
    if (!injection.trim()) return;

    setInjecting(true);
    const recordId = generateId();
    setHistory((prev) => [
      ...prev,
      {
        id: recordId,
        type: 'argument',
        content: injection,
        timestamp: Date.now(),
        status: 'pending',
      },
    ]);
    try {
      const response = await fetch(`${debatePath}/inject-evidence`, {
        method: 'POST',
        headers: requestHeaders(),
        body: JSON.stringify({ evidence: injection, source: 'user' }),
      });

      if (response.ok) {
        onInject?.(injection);
        updateHistoryStatus(recordId, 'applied');
        setInjection('');
        showToast('Evidence injected -- agents will incorporate in next round', 'success');
      } else {
        showToast('Failed to inject evidence', 'error');
        updateHistoryStatus(recordId, 'failed');
      }
    } catch (error) {
      logger.error('Failed to inject argument:', error);
      showToast('Failed to inject evidence -- check connection', 'error');
      updateHistoryStatus(recordId, 'failed');
    } finally {
      setInjecting(false);
    }
  }, [debatePath, injection, onInject, showToast, updateHistoryStatus]);

  // Handle follow-up question
  const handleFollowUp = useCallback(async () => {
    if (!followUpQuestion.trim()) return;

    setInjecting(true);
    const recordId = generateId();
    setHistory((prev) => [
      ...prev,
      {
        id: recordId,
        type: 'follow_up',
        content: followUpQuestion,
        timestamp: Date.now(),
        status: 'pending',
      },
    ]);
    try {
      const response = await fetch(`${debatePath}/nudge`, {
        method: 'POST',
        headers: requestHeaders(),
        body: JSON.stringify({ message: followUpQuestion }),
      });

      if (response.ok) {
        onInject?.(followUpQuestion);
        updateHistoryStatus(recordId, 'applied');
        setFollowUpQuestion('');
        showToast('Follow-up question added -- agents will address in next round', 'success');
      } else {
        showToast('Failed to add follow-up question', 'error');
        updateHistoryStatus(recordId, 'failed');
      }
    } catch (error) {
      logger.error('Failed to add follow-up:', error);
      showToast('Failed to add follow-up question -- check connection', 'error');
      updateHistoryStatus(recordId, 'failed');
    } finally {
      setInjecting(false);
    }
  }, [debatePath, followUpQuestion, onInject, showToast, updateHistoryStatus]);

  // Handle nudge direction
  const handleNudge = useCallback(async () => {
    if (!nudgeDirection.trim()) return;
    setInjecting(true);
    const recordId = generateId();
    setHistory((prev) => [
      ...prev,
      {
        id: recordId,
        type: 'nudge',
        content: nudgeDirection,
        timestamp: Date.now(),
        status: 'pending',
      },
    ]);
    try {
      const response = await fetch(`${debatePath}/nudge`, {
        method: 'POST',
        headers: requestHeaders(),
        body: JSON.stringify({ message: nudgeDirection }),
      });
      if (response.ok) {
        onInject?.(nudgeDirection);
        updateHistoryStatus(recordId, 'applied');
        setNudgeDirection('');
        showToast('Direction nudge applied -- debate focus will shift', 'success');
      } else {
        showToast('Failed to apply nudge', 'error');
        updateHistoryStatus(recordId, 'failed');
      }
    } catch (error) {
      logger.error('Failed to nudge direction:', error);
      showToast('Failed to apply nudge -- check connection', 'error');
      updateHistoryStatus(recordId, 'failed');
    } finally {
      setInjecting(false);
    }
  }, [debatePath, nudgeDirection, onInject, showToast, updateHistoryStatus]);

  // Handle challenge claim
  const handleChallenge = useCallback(async () => {
    if (!challengeClaim.trim()) return;
    setInjecting(true);
    const recordId = generateId();
    setHistory((prev) => [
      ...prev,
      {
        id: recordId,
        type: 'challenge',
        content: challengeClaim,
        timestamp: Date.now(),
        status: 'pending',
      },
    ]);
    try {
      const response = await fetch(`${debatePath}/challenge`, {
        method: 'POST',
        headers: requestHeaders(),
        body: JSON.stringify({ challenge: challengeClaim }),
      });
      if (response.ok) {
        onInject?.(challengeClaim);
        updateHistoryStatus(recordId, 'applied');
        setChallengeClaim('');
        showToast('Challenge injected -- agents will defend or concede', 'success');
      } else {
        showToast('Failed to inject challenge', 'error');
        updateHistoryStatus(recordId, 'failed');
      }
    } catch (error) {
      logger.error('Failed to challenge claim:', error);
      showToast('Failed to inject challenge -- check connection', 'error');
      updateHistoryStatus(recordId, 'failed');
    } finally {
      setInjecting(false);
    }
  }, [debatePath, challengeClaim, onInject, showToast, updateHistoryStatus]);

  // Handle weight change with old-vs-new comparison
  const handleWeightChange = useCallback(
    async (agent: string, weight: number) => {
      // Capture previous weights for comparison before updating
      setAgentWeights((prev) => {
        setPreviousWeights(prev);
        return prev.map((w) => (w.agent === agent ? { ...w, weight } : w));
      });

      // Show comparison for 3 seconds
      setShowWeightComparison(true);
      if (weightComparisonTimeout.current) {
        clearTimeout(weightComparisonTimeout.current);
      }
      weightComparisonTimeout.current = setTimeout(() => {
        setShowWeightComparison(false);
        setPreviousWeights(null);
      }, 3000);

      try {
        const response = await fetch(`${debatePath}/intervention/weights`, {
          method: 'POST',
          headers: requestHeaders(),
          body: JSON.stringify({ agent, weight }),
        });
        if (response.ok) {
          onWeightChange?.(agent, weight);
          addToHistory('weight_change', `${agent}: ${weight.toFixed(1)}x`);
          showToast(`${agent} weight updated to ${weight.toFixed(1)}x`, 'success');
        } else {
          showToast(`Failed to update ${agent} weight`, 'error');
          addToHistory('weight_change', `${agent}: ${weight.toFixed(1)}x (failed)`, 'failed');
        }
      } catch (error) {
        logger.error('Failed to update weight:', error);
        showToast(`Failed to update ${agent} weight -- check connection`, 'error');
        addToHistory('weight_change', `${agent}: ${weight.toFixed(1)}x (failed)`, 'failed');
      }
    },
    [debatePath, onWeightChange, addToHistory, showToast],
  );

  // Handle threshold change
  const handleThresholdChange = useCallback(
    async (threshold: number) => {
      const oldThreshold = consensusThreshold;
      setConsensusThreshold(threshold);

      try {
        const response = await fetch(`${debatePath}/intervention/threshold`, {
          method: 'POST',
          headers: requestHeaders(),
          body: JSON.stringify({ threshold }),
        });
        if (response.ok) {
          onThresholdChange?.(threshold);
          addToHistory(
            'threshold_change',
            `${Math.round(oldThreshold * 100)}% -> ${Math.round(threshold * 100)}%`,
          );
          showToast(`Consensus threshold set to ${Math.round(threshold * 100)}%`, 'info');
        } else {
          showToast('Failed to update consensus threshold', 'error');
        }
      } catch (error) {
        logger.error('Failed to update threshold:', error);
        showToast('Failed to update consensus threshold -- check connection', 'error');
      }
    },
    [debatePath, onThresholdChange, addToHistory, showToast, consensusThreshold],
  );

  if (!isActive) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <div className="text-center text-[var(--text-muted)] text-sm font-theme-data">
          Intervention controls are only available during active debates
        </div>
      </div>
    );
  }

  const totalWeight = agentWeights.reduce((sum, w) => sum + w.weight, 0);
  const previousTotalWeight = previousWeights
    ? previousWeights.reduce((sum, w) => sum + w.weight, 0)
    : 0;

  return (
    <div className="bg-[var(--surface)] border border-[var(--acid-green)]/30 relative">
      {/* Toast notifications */}
      {toasts.length > 0 && (
        <div
          className="absolute top-2 right-2 z-20 flex flex-col gap-1.5 max-w-xs"
          role="region"
          aria-label="Intervention notifications"
          aria-live="polite"
        >
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`px-3 py-2 text-xs font-theme-data border backdrop-blur-sm animate-in slide-in-from-right-4 transition-opacity duration-300 ${
                t.type === 'success'
                  ? 'bg-green-500/15 border-green-500/40 text-green-400'
                  : t.type === 'error'
                    ? 'bg-red-500/15 border-red-500/40 text-red-400'
                    : 'bg-[var(--acid-cyan)]/15 border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)]'
              }`}
            >
              <span className="mr-1.5">
                {t.type === 'success' ? '[OK]' : t.type === 'error' ? '[ERR]' : '[i]'}
              </span>
              {t.message}
            </div>
          ))}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="text-lg"></span>
          <h3 className="text-sm font-theme-data font-bold text-[var(--text)] uppercase">
            Intervention Controls
          </h3>
          {history.length > 0 && (
            <span className="text-[10px] font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 px-1.5 py-0.5">
              {history.length} actions
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-[var(--text-muted)]">
            Round {currentRound}/{totalRounds}
          </span>
          <button
            onClick={handlePauseToggle}
            disabled={pauseLoading}
            className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
              isPaused
                ? 'bg-green-500/20 text-green-400 border-green-500/30 hover:bg-green-500/30'
                : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30 hover:bg-yellow-500/30'
            }`}
          >
            {pauseLoading ? '...' : isPaused ? ' RESUME' : ' PAUSE'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--border)]">
        {[
          { id: 'inject', label: 'Inject', icon: '' },
          { id: 'nudge', label: 'Nudge', icon: '' },
          { id: 'control', label: 'Control', icon: '' },
          { id: 'weights', label: 'Weights', icon: '' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={`flex-1 px-3 py-2 text-xs font-theme-data transition-colors ${
              activeTab === tab.id
                ? 'bg-[var(--acid-green)]/10 text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                : 'text-[var(--text-muted)] hover:bg-[var(--bg)]'
            }`}
          >
            <span className="mr-1">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="p-3">
        {/* Inject Tab */}
        {activeTab === 'inject' && (
          <div className="space-y-4">
            {/* Argument Injection */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                INJECT ARGUMENT
              </label>
              <textarea
                value={injection}
                onChange={(e) => setInjection(e.target.value)}
                placeholder="Add your argument to the debate..."
                className="w-full h-24 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] font-theme-data text-sm p-2 resize-none focus:border-[var(--acid-green)] focus:outline-none"
              />
              <button
                onClick={handleInject}
                disabled={!injection.trim() || injecting}
                className="mt-2 w-full px-3 py-2 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {injecting ? 'INJECTING...' : ' INJECT ARGUMENT'}
              </button>
            </div>

            {/* Follow-up Question */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                ADD FOLLOW-UP QUESTION
              </label>
              <input
                type="text"
                value={followUpQuestion}
                onChange={(e) => setFollowUpQuestion(e.target.value)}
                placeholder="Ask a follow-up question..."
                className="w-full bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] font-theme-data text-sm p-2 focus:border-[var(--acid-green)] focus:outline-none"
              />
              <button
                onClick={handleFollowUp}
                disabled={!followUpQuestion.trim() || injecting}
                className="mt-2 w-full px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                ADD FOLLOW-UP
              </button>
            </div>
          </div>
        )}

        {/* Nudge Tab */}
        {activeTab === 'nudge' && (
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                NUDGE DIRECTION
              </label>
              <p className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                Redirect the debate focus without adding a specific argument.
              </p>
              <input
                type="text"
                value={nudgeDirection}
                onChange={(e) => setNudgeDirection(e.target.value)}
                placeholder="e.g., Consider the economic implications..."
                className="w-full bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] font-theme-data text-sm p-2 focus:border-[var(--acid-green)] focus:outline-none"
              />
              <button
                onClick={handleNudge}
                disabled={!nudgeDirection.trim() || injecting}
                className="mt-2 w-full px-3 py-2 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {injecting ? 'NUDGING...' : 'NUDGE DIRECTION'}
              </button>
            </div>
            <div>
              <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                CHALLENGE CLAIM
              </label>
              <p className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                Challenge a specific claim. Injected as a counter-argument.
              </p>
              <textarea
                value={challengeClaim}
                onChange={(e) => setChallengeClaim(e.target.value)}
                placeholder="e.g., The claim that X is incorrect because..."
                className="w-full h-20 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] font-theme-data text-sm p-2 resize-none focus:border-[var(--acid-yellow)] focus:outline-none"
              />
              <button
                onClick={handleChallenge}
                disabled={!challengeClaim.trim() || injecting}
                className="mt-2 w-full px-3 py-2 text-xs font-theme-data bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {injecting ? 'CHALLENGING...' : 'CHALLENGE CLAIM'}
              </button>
            </div>
          </div>
        )}

        {/* Control Tab */}
        {activeTab === 'control' && (
          <div className="space-y-4">
            {/* Consensus Threshold */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                CONSENSUS THRESHOLD: {Math.round(consensusThreshold * 100)}%
              </label>
              <input
                type="range"
                min="0.5"
                max="1.0"
                step="0.05"
                value={consensusThreshold}
                onChange={(e) => handleThresholdChange(parseFloat(e.target.value))}
                className="w-full accent-[var(--acid-green)]"
              />
              <div className="flex justify-between text-[10px] font-theme-data text-[var(--text-muted)] mt-1">
                <span>50%</span>
                <span>75%</span>
                <span>100%</span>
              </div>
            </div>

            {/* Quick Actions */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
                QUICK ACTIONS
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors">
                  Skip Round
                </button>
                <button className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors">
                  Add Round
                </button>
                <button className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors">
                  Force Vote
                </button>
                <button className="px-3 py-2 text-xs font-theme-data bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors">
                  End Debate
                </button>
              </div>
            </div>

            {/* Debate Status */}
            <div className="pt-3 border-t border-[var(--border)]">
              <div className="flex items-center justify-between text-xs font-theme-data">
                <span className="text-[var(--text-muted)]">Status</span>
                <span className={isPaused ? 'text-yellow-400' : 'text-green-400'}>
                  {isPaused ? ' PAUSED' : ' RUNNING'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Weights Tab */}
        {activeTab === 'weights' && (
          <div className="space-y-3">
            <div className="text-xs font-theme-data text-[var(--text-muted)] mb-3">
              Adjust agent influence on consensus:
            </div>

            {/* Weight comparison: old vs new */}
            {showWeightComparison && previousWeights && (
              <div className="space-y-1.5 mb-3" data-testid="weight-comparison">
                <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                  Previous
                </div>
                <WeightBar weights={previousWeights} totalWeight={previousTotalWeight} />
                <div className="text-[10px] font-theme-data text-[var(--acid-green)] uppercase">
                  Current
                </div>
              </div>
            )}

            {/* Current weight distribution bar -- per-agent colored */}
            <WeightBar weights={agentWeights} totalWeight={totalWeight} />
            <div className="flex justify-between text-[10px] font-theme-data text-[var(--text-muted)]">
              {agentWeights.map(({ agent, weight }) => {
                const pct = totalWeight > 0 ? (weight / totalWeight) * 100 : 0;
                const colors = getAgentColors(agent);
                return (
                  <span key={agent} className={colors.text}>
                    {agent.slice(0, 6)}: {pct.toFixed(0)}%
                  </span>
                );
              })}
            </div>
            {agentWeights.map(({ agent, weight }) => {
              const colors = getAgentColors(agent);
              return (
                <div key={agent} className="space-y-1">
                  <div className="flex items-center justify-between text-xs font-theme-data">
                    <span className={colors.text}>{agent}</span>
                    <span className={colors.text}>{weight.toFixed(1)}x</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={weight}
                    onChange={(e) => handleWeightChange(agent, parseFloat(e.target.value))}
                    className="w-full accent-[var(--acid-cyan)] h-1"
                  />
                </div>
              );
            })}
            <div className="pt-2 text-[10px] font-theme-data text-[var(--text-muted)]">
              0 = muted | 1 = normal | 2 = double influence
            </div>
          </div>
        )}
      </div>

      {/* Intervention History */}
      {history.length > 0 && (
        <div className="border-t border-[var(--border)]">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="w-full px-3 py-2 flex items-center justify-between text-[10px] font-theme-data text-[var(--text-muted)] uppercase hover:bg-[var(--bg)] transition-colors"
          >
            <span>History ({history.length})</span>
            <span>{showHistory ? '[-]' : '[+]'}</span>
          </button>
          {showHistory && (
            <div className="px-3 pb-2 space-y-1.5 max-h-[200px] overflow-y-auto">
              {history
                .slice()
                .reverse()
                .map((record) => {
                  const statusStyle = STATUS_STYLES[record.status];
                  return (
                    <div
                      key={record.id}
                      className={`flex items-start gap-2 text-[10px] font-theme-data p-1.5 border ${statusStyle.bg} ${statusStyle.border}`}
                    >
                      <span className="text-[var(--acid-cyan)] shrink-0">
                        {new Date(record.timestamp).toLocaleTimeString()}
                      </span>
                      <span className="text-[var(--acid-yellow)] shrink-0 uppercase">
                        [{TYPE_LABELS[record.type] || record.type}]
                      </span>
                      <span className="text-[var(--text-muted)] flex-1 truncate">
                        {record.content.slice(0, 80)}
                        {record.content.length > 80 ? '...' : ''}
                      </span>
                      <span className={`shrink-0 uppercase ${statusStyle.text}`}>
                        {record.status}
                      </span>
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="px-3 py-2 border-t border-[var(--border)] text-[10px] font-theme-data text-[var(--text-muted)]">
        Interventions are logged in the audit trail
      </div>
    </div>
  );
}

/** Horizontal bar chart showing per-agent weight distribution with colored segments. */
function WeightBar({ weights, totalWeight }: { weights: AgentWeight[]; totalWeight: number }) {
  return (
    <div
      className="flex h-4 rounded-sm overflow-hidden border border-[var(--border)]"
      data-testid="weight-bar"
    >
      {weights.map(({ agent, weight }, index) => {
        const pct = totalWeight > 0 ? (weight / totalWeight) * 100 : 0;
        const color = getBarColor(agent);
        return (
          <div
            key={agent}
            className="h-full transition-all duration-500 ease-in-out relative group"
            style={{
              width: `${pct}%`,
              backgroundColor: color,
              opacity: weight === 0 ? 0.1 : 0.3 + (weight / 2) * 0.5,
              borderRight: index < weights.length - 1 ? '1px solid var(--bg)' : undefined,
            }}
            title={`${agent}: ${pct.toFixed(0)}% (${weight.toFixed(1)}x)`}
          >
            {/* Hover label */}
            {pct > 15 && (
              <span className="absolute inset-0 flex items-center justify-center text-[9px] font-theme-data text-white/70 opacity-0 group-hover:opacity-100 transition-opacity">
                {agent.slice(0, 4)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default InterventionPanel;
