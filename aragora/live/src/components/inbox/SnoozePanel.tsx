'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface SnoozeSuggestion {
  snooze_until: string;
  label: string;
  reason: string;
  confidence: number;
  source: string;
}

interface SnoozedEmail {
  email_id: string;
  snooze_until: string;
  label: string;
  snoozed_at: string;
  is_due: boolean;
}

interface _SnoozeRecommendation {
  email_id: string;
  suggestions: SnoozeSuggestion[];
  recommended: SnoozeSuggestion | null;
}

interface SnoozePanelProps {
  apiBase?: string;
  userId?: string;
  authToken?: string;
  emailId?: string;
  emailSubject?: string;
  emailSender?: string;
  emailPriority?: number;
  onSnooze?: (emailId: string, snoozeUntil: Date) => void;
  onClose?: () => void;
  className?: string;
}

export function SnoozePanel({
  apiBase,
  emailId,
  emailSubject,
  emailSender,
  emailPriority,
  onSnooze,
  onClose,
  className = '',
}: SnoozePanelProps) {
  const baseUrl = apiBase ?? API_BASE_URL;
  const [suggestions, setSuggestions] = useState<SnoozeSuggestion[]>([]);
  const [recommended, setRecommended] = useState<SnoozeSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [customDate, setCustomDate] = useState('');
  const [customTime, setCustomTime] = useState('09:00');

  const fetchSuggestions = useCallback(async () => {
    if (!emailId) return;

    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${baseUrl}/api/v1/email/${emailId}/snooze-suggestions`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      // Also send as POST with body if GET doesn't work
      const body = {
        subject: emailSubject,
        sender: emailSender,
        priority: emailPriority,
        max_suggestions: 5,
      };

      const postRes = await fetch(`${baseUrl}/api/v1/email/${emailId}/snooze-suggestions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await (postRes.ok ? postRes : res).json();

      if (data.status === 'success') {
        setSuggestions(data.data.suggestions);
        setRecommended(data.data.recommended);
      } else {
        // Use default suggestions if API fails
        setDefaultSuggestions();
      }
    } catch {
      setDefaultSuggestions();
    } finally {
      setLoading(false);
    }
  }, [baseUrl, emailId, emailSubject, emailSender, emailPriority]);

  const setDefaultSuggestions = () => {
    const now = new Date();
    const tomorrow9am = new Date(now);
    tomorrow9am.setDate(tomorrow9am.getDate() + 1);
    tomorrow9am.setHours(9, 0, 0, 0);

    const nextMonday = new Date(now);
    nextMonday.setDate(now.getDate() + ((8 - now.getDay()) % 7 || 7));
    nextMonday.setHours(9, 0, 0, 0);

    const in2Hours = new Date(now.getTime() + 2 * 60 * 60 * 1000);
    const thisEvening = new Date(now);
    thisEvening.setHours(18, 0, 0, 0);

    setSuggestions([
      {
        snooze_until: in2Hours.toISOString(),
        label: 'In 2 hours',
        reason: 'Quick reminder',
        confidence: 0.8,
        source: 'quick',
      },
      {
        snooze_until: thisEvening.toISOString(),
        label: 'This evening',
        reason: 'End of day review',
        confidence: 0.7,
        source: 'quick',
      },
      {
        snooze_until: tomorrow9am.toISOString(),
        label: 'Tomorrow morning',
        reason: 'Fresh start tomorrow',
        confidence: 0.9,
        source: 'quick',
      },
      {
        snooze_until: nextMonday.toISOString(),
        label: 'Next Monday',
        reason: 'Start of next week',
        confidence: 0.6,
        source: 'quick',
      },
    ]);
  };

  useEffect(() => {
    if (emailId) {
      fetchSuggestions();
    } else {
      setDefaultSuggestions();
    }
  }, [emailId, fetchSuggestions]);

  const handleApplySnooze = async (snoozeUntil: string) => {
    if (!emailId) return;

    try {
      setApplying(true);
      const res = await fetch(`${baseUrl}/api/v1/email/${emailId}/snooze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snooze_until: snoozeUntil, label: 'Snoozed' }),
      });

      const data = await res.json();
      if (data.status === 'success') {
        onSnooze?.(emailId, new Date(snoozeUntil));
        onClose?.();
      } else {
        setError(data.message || 'Failed to apply snooze');
      }
    } catch {
      setError('Failed to apply snooze');
    } finally {
      setApplying(false);
    }
  };

  const handleCustomSnooze = () => {
    if (!customDate) {
      setError('Please select a date');
      return;
    }
    const snoozeDateTime = new Date(`${customDate}T${customTime}`);
    if (snoozeDateTime <= new Date()) {
      setError('Please select a future date/time');
      return;
    }
    handleApplySnooze(snoozeDateTime.toISOString());
  };

  const formatSnoozeTime = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);

    const isToday = date.toDateString() === now.toDateString();
    const isTomorrow = date.toDateString() === tomorrow.toDateString();

    const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (isToday) return `Today at ${timeStr}`;
    if (isTomorrow) return `Tomorrow at ${timeStr}`;
    return `${date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })} at ${timeStr}`;
  };

  const getSourceIcon = (source: string) => {
    switch (source) {
      case 'calendar':
        return '📅';
      case 'sender_pattern':
        return '👤';
      case 'priority_decay':
        return '📉';
      case 'work_schedule':
        return '💼';
      default:
        return '⏰';
    }
  };

  return (
    <div className={`bg-[var(--surface)] border border-[var(--border)] rounded ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
        <div>
          <h3 className="font-theme-data text-sm font-medium text-[var(--text)]">Snooze Email</h3>
          {emailSubject && (
            <p className="text-xs text-[var(--text-muted)] truncate max-w-xs mt-1">
              {emailSubject}
            </p>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text)] p-1"
          >
            ✕
          </button>
        )}
      </div>

      {/* Content */}
      <div className="p-4">
        {loading ? (
          <div className="text-center py-4">
            <div className="text-[var(--text-muted)] text-sm font-theme-data">
              Getting smart suggestions...
            </div>
          </div>
        ) : (
          <>
            {/* Recommended */}
            {recommended && (
              <div className="mb-4">
                <div className="text-xs text-[var(--text-muted)] font-theme-data mb-2">
                  RECOMMENDED
                </div>
                <button
                  onClick={() => handleApplySnooze(recommended.snooze_until)}
                  disabled={applying}
                  className="w-full p-3 bg-blue-500/20 border border-blue-500/40 rounded hover:bg-blue-500/30 transition-colors text-left"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-theme-data text-blue-400">
                        {recommended.label}
                      </div>
                      <div className="text-xs text-[var(--text-muted)]">
                        {formatSnoozeTime(recommended.snooze_until)}
                      </div>
                    </div>
                    <span className="text-blue-400">→</span>
                  </div>
                  {recommended.reason && (
                    <div className="text-xs text-[var(--text-muted)] mt-1">
                      {recommended.reason}
                    </div>
                  )}
                </button>
              </div>
            )}

            {/* Other Suggestions */}
            <div className="space-y-2">
              <div className="text-xs text-[var(--text-muted)] font-theme-data">QUICK OPTIONS</div>
              {suggestions
                .filter((s) => s !== recommended)
                .map((suggestion, index) => (
                  <button
                    key={index}
                    onClick={() => handleApplySnooze(suggestion.snooze_until)}
                    disabled={applying}
                    className="w-full p-2 border border-[var(--border)] rounded hover:bg-[var(--surface-hover)] transition-colors text-left flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <span>{getSourceIcon(suggestion.source)}</span>
                      <div>
                        <div className="text-sm font-theme-data text-[var(--text)]">
                          {suggestion.label}
                        </div>
                        <div className="text-xs text-[var(--text-muted)]">
                          {formatSnoozeTime(suggestion.snooze_until)}
                        </div>
                      </div>
                    </div>
                    {suggestion.confidence > 0.8 && (
                      <span className="text-xs text-green-400">★</span>
                    )}
                  </button>
                ))}
            </div>

            {/* Custom Date/Time */}
            <div className="mt-4 pt-4 border-t border-[var(--border)]">
              <div className="text-xs text-[var(--text-muted)] font-theme-data mb-2">
                CUSTOM TIME
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={customDate}
                  onChange={(e) => setCustomDate(e.target.value)}
                  min={new Date().toISOString().split('T')[0]}
                  className="flex-1 px-2 py-1 text-sm font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)]"
                />
                <input
                  type="time"
                  value={customTime}
                  onChange={(e) => setCustomTime(e.target.value)}
                  className="w-24 px-2 py-1 text-sm font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)]"
                />
                <button
                  onClick={handleCustomSnooze}
                  disabled={applying || !customDate}
                  className="px-3 py-1 text-sm font-theme-data bg-[var(--primary)] text-white rounded hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  Set
                </button>
              </div>
            </div>

            {/* Error */}
            {error && <div className="mt-3 text-xs text-red-400 font-theme-data">{error}</div>}
          </>
        )}
      </div>
    </div>
  );
}

// Snoozed Emails List Component
interface SnoozedEmailsListProps {
  userId?: string;
  onWake?: (emailId: string) => void;
  className?: string;
}

export function SnoozedEmailsList({
  userId: _userId = 'default',
  onWake,
  className = '',
}: SnoozedEmailsListProps) {
  const [snoozed, setSnoozed] = useState<SnoozedEmail[]>([]);
  const [loading, setLoading] = useState(true);
  const [_error, setError] = useState<string | null>(null);
  const baseUrl = API_BASE_URL;

  const fetchSnoozed = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${baseUrl}/api/v1/email/snoozed`);
      const data = await res.json();
      if (data.status === 'success') {
        setSnoozed(data.data.snoozed);
      }
    } catch {
      setError('Failed to load snoozed emails');
    } finally {
      setLoading(false);
    }
  }, [baseUrl]);

  useEffect(() => {
    fetchSnoozed();
  }, [fetchSnoozed]);

  const handleCancel = async (emailId: string) => {
    try {
      const res = await fetch(`${baseUrl}/api/v1/email/${emailId}/snooze`, { method: 'DELETE' });
      const data = await res.json();
      if (data.status === 'success') {
        onWake?.(emailId);
        fetchSnoozed();
      }
    } catch {
      setError('Failed to cancel snooze');
    }
  };

  const dueCount = snoozed.filter((s) => s.is_due).length;

  return (
    <div className={`bg-[var(--surface)] border border-[var(--border)] rounded ${className}`}>
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-theme-data text-sm font-medium text-[var(--text)]">Snoozed Emails</h3>
          {dueCount > 0 && (
            <span className="px-2 py-0.5 text-xs rounded bg-blue-500/20 text-blue-400">
              {dueCount} due
            </span>
          )}
        </div>
        <span className="text-xs text-[var(--text-muted)] font-theme-data">
          {snoozed.length} snoozed
        </span>
      </div>

      <div className="max-h-[300px] overflow-y-auto">
        {loading ? (
          <div className="p-4 text-center text-[var(--text-muted)] text-sm font-theme-data">
            Loading...
          </div>
        ) : snoozed.length === 0 ? (
          <div className="p-4 text-center text-[var(--text-muted)] text-sm font-theme-data">
            No snoozed emails
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {snoozed.map((item) => (
              <div
                key={item.email_id}
                className={`p-3 flex items-center justify-between ${item.is_due ? 'bg-blue-500/10' : ''}`}
              >
                <div>
                  <div className="text-sm font-theme-data text-[var(--text)]">{item.label}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    Until{' '}
                    {new Date(item.snooze_until).toLocaleString([], {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })}
                  </div>
                </div>
                <button
                  onClick={() => handleCancel(item.email_id)}
                  className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] rounded"
                >
                  {item.is_due ? 'Open' : 'Cancel'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default SnoozePanel;
