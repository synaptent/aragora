'use client';

import { useState, useEffect, useCallback } from 'react';
import { EmailDetailModal } from './EmailDetailModal';
import { logger } from '@/utils/logger';

// Priority levels from the email prioritization service
export type EmailPriority = 'critical' | 'high' | 'medium' | 'low' | 'defer' | 'spam' | 'blocked';

export interface PrioritizedEmail {
  id: string;
  subject: string;
  from_address: string;
  snippet: string;
  date: string;
  thread_id?: string;
  labels?: string[];
  read?: boolean;
  category?: string;
  reasoning?: string;
  // Prioritization results
  priority: EmailPriority;
  confidence: number;
  score: number;
  tier_used: number;
  rationale?: string;
  // Context boosts
  slack_boost?: number;
  drive_boost?: number;
  calendar_boost?: number;
}

interface RankedInboxResponse {
  emails: PrioritizedEmail[];
  total_count: number;
  processing_time_ms: number;
  tiers_summary: { tier_1_count: number; tier_2_count: number; tier_3_count: number };
}

// Legacy email format from older API
interface LegacyEmail {
  id: string;
  subject: string;
  sender: string;
  snippet: string;
  date: string;
  thread_id?: string;
  labels?: string[];
  priority_score: number;
}

export interface PriorityInboxListProps {
  // API configuration (for self-fetching mode)
  apiBase?: string;
  userId?: string;
  authToken?: string;
  // Controlled mode props
  emails?: PrioritizedEmail[];
  loading?: boolean;
  selectedId?: string;
  onSelect?: (email: PrioritizedEmail) => void;
  onRefresh?: () => void;
}

const PRIORITY_CONFIG: Record<EmailPriority, { color: string; icon: string; label: string }> = {
  critical: {
    color: 'text-red-400 border-red-500/40 bg-red-500/10',
    icon: '🔴',
    label: 'CRITICAL',
  },
  high: {
    color: 'text-orange-400 border-orange-500/40 bg-orange-500/10',
    icon: '🟠',
    label: 'HIGH',
  },
  medium: {
    color: 'text-yellow-400 border-yellow-500/40 bg-yellow-500/10',
    icon: '🟡',
    label: 'MEDIUM',
  },
  low: { color: 'text-blue-400 border-blue-500/40 bg-blue-500/10', icon: '🔵', label: 'LOW' },
  defer: { color: 'text-gray-400 border-gray-500/40 bg-gray-500/10', icon: '⚪', label: 'DEFER' },
  spam: { color: 'text-red-600 border-red-600/40 bg-red-600/10', icon: '🚫', label: 'SPAM' },
  blocked: {
    color: 'text-slate-500 border-slate-600/40 bg-slate-600/10',
    icon: '⛔',
    label: 'BLOCKED',
  },
};

export function PriorityInboxList({
  apiBase,
  userId,
  authToken,
  emails: controlledEmails,
  loading: controlledLoading,
  selectedId: _selectedId,
  onSelect: _onSelect,
  onRefresh: _onRefresh,
}: PriorityInboxListProps) {
  // Use controlled mode if emails are provided
  const isControlled = controlledEmails !== undefined;
  const [internalEmails, setInternalEmails] = useState<PrioritizedEmail[]>([]);
  const [internalLoading, setInternalLoading] = useState(true);

  // Use controlled or internal state
  const emails = isControlled ? controlledEmails : internalEmails;
  const setEmails = isControlled ? () => {} : setInternalEmails;
  const isLoading = isControlled ? (controlledLoading ?? false) : internalLoading;
  const setIsLoading = isControlled ? () => {} : setInternalLoading;
  const [error, setError] = useState<string | null>(null);
  const [processingTime, setProcessingTime] = useState<number | null>(null);
  const [tiersSummary, setTiersSummary] = useState<RankedInboxResponse['tiers_summary'] | null>(
    null,
  );
  const [selectedEmail, setSelectedEmail] = useState<PrioritizedEmail | null>(null);
  const [modalEmailId, setModalEmailId] = useState<string | null>(null);
  const [filter, setFilter] = useState<EmailPriority | 'all'>('all');
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchEmails = useCallback(
    async (showRefresh = false) => {
      if (showRefresh) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setError(null);

      try {
        // Use the new email prioritization API
        const response = await fetch(`${apiBase}/api/email/inbox?user_id=${userId}`, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });

        if (!response.ok) {
          // Fallback to legacy Gmail API if new API not available
          const legacyResponse = await fetch(
            `${apiBase}/api/gmail/inbox/priority?user_id=${userId}`,
            { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
          );
          if (!legacyResponse.ok) throw new Error('Failed to fetch emails');
          const legacyData = await legacyResponse.json();
          // Map legacy format to new format
          const mappedEmails: PrioritizedEmail[] = ((legacyData.emails || []) as LegacyEmail[]).map(
            (e) => ({
              ...e,
              from_address: e.sender,
              priority:
                e.priority_score > 80
                  ? 'critical'
                  : e.priority_score > 60
                    ? 'high'
                    : e.priority_score > 40
                      ? 'medium'
                      : e.priority_score > 20
                        ? 'low'
                        : 'defer',
              confidence: e.priority_score / 100,
              score: e.priority_score,
              tier_used: 1,
            }),
          );
          setEmails(mappedEmails);
          return;
        }

        const data: RankedInboxResponse = await response.json();
        setEmails(data.emails || []);
        setProcessingTime(data.processing_time_ms);
        setTiersSummary(data.tiers_summary);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps -- state setters are stable
    },
    [apiBase, userId, authToken],
  );

  useEffect(() => {
    fetchEmails();
  }, [fetchEmails]);

  const handleFeedback = useCallback(
    async (emailId: string, isCorrect: boolean) => {
      try {
        await fetch(`${apiBase}/api/email/feedback`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify({ email_id: emailId, user_id: userId, is_correct: isCorrect }),
        });
      } catch (err) {
        logger.error('Failed to send feedback:', err);
      }
    },
    [apiBase, userId, authToken],
  );

  const filteredEmails = filter === 'all' ? emails : emails.filter((e) => e.priority === filter);

  const priorityCounts = emails.reduce(
    (acc, e) => {
      acc[e.priority] = (acc[e.priority] || 0) + 1;
      return acc;
    },
    {} as Record<EmailPriority, number>,
  );

  if (isLoading) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
        <h3 className="text-[var(--accent)] font-theme-data text-sm mb-4">AI Priority Inbox</h3>
        <div className="text-center py-8 text-text-muted font-theme-data text-sm">
          <div className="animate-pulse mb-2">Analyzing emails with AI...</div>
          <div className="text-xs text-[var(--accent)]/60">3-tier prioritization in progress</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
        <h3 className="text-[var(--accent)] font-theme-data text-sm mb-4">AI Priority Inbox</h3>
        <div className="text-center py-8 text-red-400 font-theme-data text-sm">{error}</div>
        <button
          onClick={() => fetchEmails()}
          className="mt-4 w-full px-3 py-2 text-sm font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded"
        >
          Retry
        </button>
      </div>
    );
  }

  if (emails.length === 0) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
        <h3 className="text-[var(--accent)] font-theme-data text-sm mb-4">AI Priority Inbox</h3>
        <div className="text-center py-8 text-text-muted font-theme-data text-sm">
          No emails to prioritize. Sync your inbox first.
        </div>
      </div>
    );
  }

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[var(--accent)] font-theme-data text-sm">AI Priority Inbox</h3>
        <div className="flex items-center gap-2">
          {processingTime && (
            <span className="text-xs text-text-muted font-theme-data">{processingTime}ms</span>
          )}
          <button
            onClick={() => fetchEmails(true)}
            disabled={isRefreshing}
            className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 disabled:opacity-50 rounded"
          >
            {isRefreshing ? '...' : '↻'}
          </button>
        </div>
      </div>

      {/* Tier Summary */}
      {tiersSummary && (
        <div className="mb-4 flex gap-2 text-xs font-theme-data">
          <span className="px-2 py-1 bg-[var(--accent)]/10 border border-[var(--accent)]/20 rounded text-[var(--accent)]">
            T1: {tiersSummary.tier_1_count}
          </span>
          <span className="px-2 py-1 bg-blue-500/10 border border-blue-500/20 rounded text-blue-400">
            T2: {tiersSummary.tier_2_count}
          </span>
          <span className="px-2 py-1 bg-purple-500/10 border border-purple-500/20 rounded text-purple-400">
            T3: {tiersSummary.tier_3_count}
          </span>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="mb-4 flex flex-wrap gap-1">
        <button
          onClick={() => setFilter('all')}
          className={`px-2 py-1 text-xs font-theme-data rounded ${
            filter === 'all'
              ? 'bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)]'
              : 'bg-surface border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          All ({emails.length})
        </button>
        {(['critical', 'high', 'medium', 'low', 'defer', 'blocked'] as EmailPriority[]).map(
          (priority) => (
            <button
              key={priority}
              onClick={() => setFilter(priority)}
              className={`px-2 py-1 text-xs font-theme-data rounded flex items-center gap-1 ${
                filter === priority
                  ? PRIORITY_CONFIG[priority].color + ' border'
                  : 'bg-surface border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)]'
              }`}
            >
              <span>{PRIORITY_CONFIG[priority].icon}</span>
              <span>{priorityCounts[priority] || 0}</span>
            </button>
          ),
        )}
      </div>

      {/* Email List */}
      <div className="space-y-2 max-h-[500px] overflow-y-auto">
        {filteredEmails.map((email) => {
          const config = PRIORITY_CONFIG[email.priority];
          return (
            <div
              key={email.id}
              onClick={() => setSelectedEmail(selectedEmail?.id === email.id ? null : email)}
              className={`border rounded cursor-pointer transition-all ${
                selectedEmail?.id === email.id
                  ? 'bg-[var(--accent)]/10 border-[var(--accent)]'
                  : 'border-[var(--accent)]/20 bg-bg/30 hover:bg-bg/50'
              }`}
            >
              <div className="p-3">
                <div className="flex items-start justify-between mb-1 gap-2">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span
                      className={`px-1.5 py-0.5 text-xs font-theme-data rounded ${config.color}`}
                    >
                      {config.icon}
                    </span>
                    <span className="text-text font-theme-data text-sm truncate flex-1">
                      {email.subject || '(No subject)'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className={`text-xs font-theme-data ${config.color.split(' ')[0]}`}>
                      {Math.round(email.confidence * 100)}%
                    </span>
                    <span className="text-text-muted text-xs">T{email.tier_used}</span>
                  </div>
                </div>
                <div className="flex justify-between text-text-muted text-xs">
                  <span className="truncate max-w-[60%]">{email.from_address}</span>
                  <span>{email.date}</span>
                </div>
                <p className="text-text-muted text-xs mt-1 truncate">{email.snippet}</p>

                {/* Context boosts */}
                {(email.slack_boost || email.drive_boost || email.calendar_boost) && (
                  <div className="mt-2 flex gap-1">
                    {email.slack_boost && email.slack_boost > 0 && (
                      <span className="px-1 py-0.5 text-xs bg-purple-500/10 text-purple-400 rounded">
                        📱+{Math.round(email.slack_boost * 100)}%
                      </span>
                    )}
                    {email.drive_boost && email.drive_boost > 0 && (
                      <span className="px-1 py-0.5 text-xs bg-blue-500/10 text-blue-400 rounded">
                        📁+{Math.round(email.drive_boost * 100)}%
                      </span>
                    )}
                    {email.calendar_boost && email.calendar_boost > 0 && (
                      <span className="px-1 py-0.5 text-xs bg-green-500/10 text-green-400 rounded">
                        📅+{Math.round(email.calendar_boost * 100)}%
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Expanded View */}
              {selectedEmail?.id === email.id && (
                <div className="border-t border-[var(--accent)]/20 p-3 bg-surface/30">
                  {email.rationale && (
                    <div className="mb-3">
                      <span className="text-[var(--accent)] text-xs font-theme-data">
                        AI Rationale:
                      </span>
                      <p className="text-text-muted text-xs mt-1">{email.rationale}</p>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex items-center justify-between gap-2 mt-2">
                    <div className="flex items-center gap-2">
                      <span className="text-text-muted text-xs">Priority correct?</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleFeedback(email.id, true);
                        }}
                        className="px-2 py-1 text-xs bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 rounded"
                      >
                        Yes
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleFeedback(email.id, false);
                        }}
                        className="px-2 py-1 text-xs bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 rounded"
                      >
                        No
                      </button>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setModalEmailId(email.id);
                      }}
                      className="px-3 py-1 text-xs bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 rounded font-theme-data"
                    >
                      View Full Email
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Email Detail Modal */}
      {modalEmailId && (
        <EmailDetailModal
          emailId={modalEmailId}
          apiBase={apiBase || ''}
          userId={userId || 'default'}
          authToken={authToken}
          onClose={() => setModalEmailId(null)}
          onFeedback={handleFeedback}
        />
      )}
    </div>
  );
}
