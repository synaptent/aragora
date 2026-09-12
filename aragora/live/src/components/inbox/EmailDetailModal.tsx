'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { sanitizeHtml } from '@/utils/sanitize';
import { MultiAgentAnalysis } from './MultiAgentAnalysis';

type EmailPriority = 'critical' | 'high' | 'medium' | 'low' | 'defer';

interface EmailDetail {
  id: string;
  thread_id?: string;
  subject: string;
  from_address: string;
  to_addresses?: string[];
  date: string;
  body_text?: string;
  body_html?: string;
  snippet: string;
  labels?: string[];
  // Prioritization
  priority: EmailPriority;
  confidence: number;
  score: number;
  tier_used: number;
  rationale?: string;
  debate_id?: string;
  // Score breakdown
  sender_score?: number;
  urgency_score?: number;
  context_score?: number;
  time_score?: number;
  // Context boosts
  slack_boost?: number;
  drive_boost?: number;
  calendar_boost?: number;
}

interface EmailDetailModalProps {
  emailId: string;
  apiBase: string;
  userId: string;
  authToken?: string;
  onClose: () => void;
  onFeedback?: (emailId: string, isCorrect: boolean) => void;
}

const PRIORITY_CONFIG: Record<
  EmailPriority,
  { color: string; bgColor: string; icon: string; label: string }
> = {
  critical: {
    color: 'text-red-400',
    bgColor: 'bg-red-500/10 border-red-500/40',
    icon: '!',
    label: 'CRITICAL',
  },
  high: {
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10 border-orange-500/40',
    icon: '^',
    label: 'HIGH',
  },
  medium: {
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/10 border-yellow-500/40',
    icon: '-',
    label: 'MEDIUM',
  },
  low: {
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10 border-blue-500/40',
    icon: '_',
    label: 'LOW',
  },
  defer: {
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10 border-gray-500/40',
    icon: '.',
    label: 'DEFER',
  },
};

const TIER_DESCRIPTIONS: Record<number, string> = {
  1: 'Rule-based (<200ms)',
  2: 'Lightweight Agent (<500ms)',
  3: 'Multi-Agent Debate',
};

function ScoreBar({ label, value, color }: { label: string; value: number; color: string }) {
  const percentage = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <span className="text-text-muted text-xs font-theme-data w-20">{label}</span>
      <div className="flex-1 h-2 bg-bg rounded overflow-hidden">
        <div
          className={`h-full ${color} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-text text-xs font-theme-data w-10 text-right">{percentage}%</span>
    </div>
  );
}

export function EmailDetailModal({
  emailId,
  apiBase,
  userId,
  authToken,
  onClose,
  onFeedback,
}: EmailDetailModalProps) {
  const [email, setEmail] = useState<EmailDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showHtml, setShowHtml] = useState(false);
  const [feedbackGiven, setFeedbackGiven] = useState<boolean | null>(null);

  const fetchEmail = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/api/email/message/${emailId}?user_id=${userId}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });

      if (!response.ok) {
        // Fallback to Gmail API
        const legacyResponse = await fetch(
          `${apiBase}/api/gmail/message/${emailId}?user_id=${userId}`,
          { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
        );
        if (!legacyResponse.ok) throw new Error('Failed to fetch email');
        const data = await legacyResponse.json();
        setEmail(data);
        return;
      }

      const data = await response.json();
      setEmail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  }, [apiBase, emailId, userId, authToken]);

  useEffect(() => {
    fetchEmail();
  }, [fetchEmail]);

  // Close on Escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  const handleFeedback = (isCorrect: boolean) => {
    setFeedbackGiven(isCorrect);
    onFeedback?.(emailId, isCorrect);
  };

  const openInGmail = () => {
    const gmailUrl = `https://mail.google.com/mail/u/0/#inbox/${emailId}`;
    window.open(gmailUrl, '_blank');
  };

  if (isLoading) {
    return (
      <ModalWrapper onClose={onClose}>
        <div className="text-center py-12">
          <div className="animate-pulse text-[var(--accent)] font-theme-data">Loading email...</div>
        </div>
      </ModalWrapper>
    );
  }

  if (error || !email) {
    return (
      <ModalWrapper onClose={onClose}>
        <div className="text-center py-12">
          <div className="text-red-400 font-theme-data mb-4">{error || 'Email not found'}</div>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded"
          >
            Close
          </button>
        </div>
      </ModalWrapper>
    );
  }

  const config = PRIORITY_CONFIG[email.priority];

  return (
    <ModalWrapper onClose={onClose}>
      {/* Header */}
      <div className="border-b border-[var(--accent)]/30 pb-4 mb-4">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-theme-data text-text flex-1">
            {email.subject || '(No subject)'}
          </h2>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text text-xl"
            aria-label="Close"
          >
            &times;
          </button>
        </div>
        <div className="mt-2 text-sm font-theme-data text-text-muted">
          <div>
            From: <span className="text-text">{email.from_address}</span>
          </div>
          {email.to_addresses && email.to_addresses.length > 0 && (
            <div>
              To: <span className="text-text">{email.to_addresses.join(', ')}</span>
            </div>
          )}
          <div>
            Date: <span className="text-text">{email.date}</span>
          </div>
        </div>
      </div>

      {/* Priority Explanation Panel */}
      <div className={`border rounded p-4 mb-4 ${config.bgColor}`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className={`text-2xl font-bold font-theme-data ${config.color}`}>
              [{config.icon}]
            </span>
            <div>
              <div className={`text-sm font-bold font-theme-data ${config.color}`}>
                {config.label} Priority
              </div>
              <div className="text-xs text-text-muted">
                {Math.round(email.confidence * 100)}% confidence
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-text-muted font-theme-data">Tier {email.tier_used}</div>
            <div className="text-xs text-text-muted">{TIER_DESCRIPTIONS[email.tier_used]}</div>
          </div>
        </div>

        {/* AI Rationale */}
        {email.rationale && (
          <div className="mb-4 p-3 bg-bg/50 rounded">
            <div className="text-xs text-[var(--accent)] font-theme-data mb-1">AI Analysis:</div>
            <p className="text-sm text-text">{email.rationale}</p>
          </div>
        )}

        {/* Score Breakdown */}
        {(email.sender_score !== undefined || email.urgency_score !== undefined) && (
          <div className="space-y-2 mb-4">
            <div className="text-xs text-text-muted font-theme-data mb-2">Score Breakdown:</div>
            {email.sender_score !== undefined && (
              <ScoreBar label="Sender" value={email.sender_score} color="bg-purple-500" />
            )}
            {email.urgency_score !== undefined && (
              <ScoreBar label="Urgency" value={email.urgency_score} color="bg-red-500" />
            )}
            {email.context_score !== undefined && (
              <ScoreBar label="Context" value={email.context_score} color="bg-blue-500" />
            )}
            {email.time_score !== undefined && (
              <ScoreBar label="Time" value={email.time_score} color="bg-yellow-500" />
            )}
          </div>
        )}

        {/* Context Boosts */}
        {(email.slack_boost || email.drive_boost || email.calendar_boost) && (
          <div className="flex flex-wrap gap-2 mb-4">
            <span className="text-xs text-text-muted font-theme-data">Context Boosts:</span>
            {email.slack_boost && email.slack_boost > 0 && (
              <span className="px-2 py-1 text-xs bg-purple-500/20 text-purple-400 rounded font-theme-data">
                Slack +{Math.round(email.slack_boost * 100)}%
              </span>
            )}
            {email.drive_boost && email.drive_boost > 0 && (
              <span className="px-2 py-1 text-xs bg-blue-500/20 text-blue-400 rounded font-theme-data">
                Drive +{Math.round(email.drive_boost * 100)}%
              </span>
            )}
            {email.calendar_boost && email.calendar_boost > 0 && (
              <span className="px-2 py-1 text-xs bg-green-500/20 text-green-400 rounded font-theme-data">
                Calendar +{Math.round(email.calendar_boost * 100)}%
              </span>
            )}
          </div>
        )}

        {/* Debate Link (Tier 3) */}
        {email.tier_used === 3 && email.debate_id && (
          <div className="mb-4">
            <Link
              href={`/debates/${email.debate_id}`}
              className="text-xs text-[var(--acid-cyan)] hover:underline font-theme-data"
            >
              View AI Debate &rarr;
            </Link>
          </div>
        )}

        {/* Feedback */}
        <div className="flex items-center gap-3 pt-3 border-t border-[var(--accent)]/20">
          <span className="text-xs text-text-muted font-theme-data">Is this priority correct?</span>
          {feedbackGiven === null ? (
            <>
              <button
                onClick={() => handleFeedback(true)}
                className="px-3 py-1 text-xs bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 rounded font-theme-data"
              >
                Yes
              </button>
              <button
                onClick={() => handleFeedback(false)}
                className="px-3 py-1 text-xs bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 rounded font-theme-data"
              >
                No
              </button>
            </>
          ) : (
            <span className="text-xs text-[var(--accent)] font-theme-data">
              Thanks for your feedback!
            </span>
          )}
        </div>

        {/* Multi-Agent Deep Analysis (Tier 3 upgrade) */}
        {email.tier_used < 3 && (
          <MultiAgentAnalysis
            apiBase={apiBase}
            userId={userId}
            authToken={authToken}
            email={{
              id: email.id,
              subject: email.subject,
              body: email.body_text,
              from_address: email.from_address,
              snippet: email.snippet,
              date: email.date,
            }}
          />
        )}
      </div>

      {/* Email Body */}
      <div className="border border-[var(--accent)]/20 rounded">
        <div className="flex items-center justify-between p-2 border-b border-[var(--accent)]/20 bg-surface/30">
          <span className="text-xs text-text-muted font-theme-data">Email Content</span>
          <div className="flex gap-2">
            {email.body_html && (
              <button
                onClick={() => setShowHtml(!showHtml)}
                className={`px-2 py-1 text-xs font-theme-data rounded ${
                  showHtml
                    ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'text-text-muted hover:text-[var(--accent)]'
                }`}
              >
                HTML
              </button>
            )}
            <button
              onClick={openInGmail}
              className="px-2 py-1 text-xs text-[var(--acid-cyan)] hover:underline font-theme-data"
            >
              Open in Gmail
            </button>
          </div>
        </div>
        <div className="p-4 max-h-[300px] overflow-y-auto">
          {showHtml && email.body_html ? (
            <div
              className="text-sm text-text prose prose-invert prose-sm max-w-none"
              dangerouslySetInnerHTML={{ __html: sanitizeHtml(email.body_html) }}
            />
          ) : (
            <pre className="text-sm text-text font-theme-data whitespace-pre-wrap">
              {email.body_text || email.snippet || '(No content)'}
            </pre>
          )}
        </div>
      </div>

      {/* Labels */}
      {email.labels && email.labels.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1">
          {email.labels.map((label) => (
            <span
              key={label}
              className="px-2 py-0.5 text-xs bg-surface border border-[var(--accent)]/20 rounded text-text-muted font-theme-data"
            >
              {label}
            </span>
          ))}
        </div>
      )}
    </ModalWrapper>
  );
}

function ModalWrapper({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="email-modal-title"
        className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-bg border border-[var(--accent)]/30 rounded-lg p-6 shadow-2xl"
      >
        <h2 id="email-modal-title" className="sr-only">
          Email Details
        </h2>
        {children}
      </div>
    </div>
  );
}
