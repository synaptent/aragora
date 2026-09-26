'use client';

import { useState, useEffect } from 'react';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { API_BASE_URL } from '@/config';

interface Moment {
  id: string;
  moment_type: string;
  agent_name: string;
  description: string;
  significance_score: number;
  timestamp: string | null;
  debate_id: string | null;
}

interface AgentMomentsModalProps {
  agentName: string;
  onClose: () => void;
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function AgentMomentsModal({
  agentName,
  onClose,
  apiBase = DEFAULT_API_BASE,
}: AgentMomentsModalProps) {
  const [moments, setMoments] = useState<Moment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const focusTrapRef = useFocusTrap<HTMLDivElement>({
    isActive: true, // Modal is always active when rendered
    onEscape: onClose,
  });

  useEffect(() => {
    async function fetchMoments() {
      try {
        setLoading(true);
        const res = await fetch(`${apiBase}/api/agent/${agentName}/moments?limit=20`);
        if (res.ok) {
          const data = await res.json();
          setMoments(data.moments || []);
        } else {
          setError('Failed to load moments');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch');
      } finally {
        setLoading(false);
      }
    }
    fetchMoments();
  }, [agentName, apiBase]);

  const getMomentIcon = (type: string): string => {
    switch (type.toLowerCase()) {
      case 'upset_victory':
        return '🏆';
      case 'calibration_vindication':
        return '🎯';
      case 'streak_achievement':
        return '🔥';
      case 'domain_mastery':
        return '👑';
      case 'consensus_breakthrough':
        return '⚡';
      case 'position_reversal':
        return '🔄';
      case 'breakthrough':
        return '⚡';
      case 'first_win':
        return '🌟';
      case 'comeback':
        return '💪';
      default:
        return '📌';
    }
  };

  const getSignificanceColor = (sig: number): string => {
    if (sig >= 0.8) return 'text-yellow-400';
    if (sig >= 0.6) return 'text-green-400';
    if (sig >= 0.4) return 'text-blue-400';
    return 'text-text-muted';
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="moments-modal-title"
    >
      <div
        ref={focusTrapRef}
        className="bg-surface border border-border rounded-lg p-6 max-w-lg w-full mx-4 max-h-[80vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h3 id="moments-modal-title" className="text-lg font-semibold text-text">
            {agentName} - Moments Timeline
          </h3>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text text-xl focus:outline-none focus:ring-2 focus:ring-accent rounded"
            aria-label="Close modal"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {loading && <div className="text-center text-text-muted py-8">Loading moments...</div>}

          {error && <div className="text-center text-red-400 py-8">{error}</div>}

          {!loading && !error && moments.length === 0 && (
            <div className="text-center text-text-muted py-8">
              No significant moments recorded yet.
            </div>
          )}

          {!loading && !error && moments.length > 0 && (
            <div className="space-y-3">
              {moments.map((moment) => (
                <div
                  key={moment.id}
                  className="p-3 bg-bg border border-border rounded-lg hover:border-accent/50 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <span className="text-2xl">{getMomentIcon(moment.moment_type)}</span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-text">
                          {moment.moment_type
                            .replace(/_/g, ' ')
                            .replace(/\b\w/g, (c) => c.toUpperCase())}
                        </span>
                        <span
                          className={`text-xs ${getSignificanceColor(moment.significance_score)}`}
                        >
                          {(moment.significance_score * 100).toFixed(0)}% significance
                        </span>
                      </div>
                      <p className="text-sm text-text-muted">{moment.description}</p>
                      {moment.debate_id && (
                        <p className="text-xs text-text-muted/70 mt-1">
                          Debate: {moment.debate_id}
                        </p>
                      )}
                      {moment.timestamp && (
                        <p className="text-xs text-text-muted/50 mt-1">
                          {new Date(moment.timestamp).toLocaleString()}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-4 pt-4 border-t border-border flex justify-end">
          <button
            onClick={onClose}
            aria-label="Close moments timeline"
            className="px-4 py-2 bg-surface border border-border rounded text-sm text-text hover:bg-surface-hover"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
