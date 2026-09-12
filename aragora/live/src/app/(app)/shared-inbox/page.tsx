'use client';

/**
 * Shared Inbox Dashboard - Team Collaboration Email Management
 *
 * Features:
 * - List of shared inboxes
 * - Message queue with assignment/status
 * - Routing rules management
 * - Team activity overview
 */

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useAuth } from '@/context/AuthContext';

interface SharedInbox {
  id: string;
  workspace_id: string;
  name: string;
  description?: string;
  email_address?: string;
  connector_type?: string;
  team_members: string[];
  admins: string[];
  message_count: number;
  unread_count: number;
  created_at: string;
}

interface SharedInboxMessage {
  id: string;
  inbox_id: string;
  email_id: string;
  subject: string;
  from_address: string;
  snippet: string;
  received_at: string;
  status: string;
  assigned_to?: string;
  tags: string[];
  priority?: string;
  trust_wedge?: {
    receipt: { receipt_id: string; state: string; canonical_receipt_id?: string | null };
    decision: { final_action: string };
  } | null;
}

interface RoutingRule {
  id: string;
  name: string;
  workspace_id: string;
  conditions: Array<{ field: string; operator: string; value: string }>;
  actions: Array<{ type: string; target?: string }>;
  priority: number;
  enabled: boolean;
  stats: { total_matches: number };
}

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-acid-blue/20 text-acid-blue border-acid-blue/40',
  assigned: 'bg-acid-purple/20 text-acid-purple border-acid-purple/40',
  in_progress: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40',
  waiting: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
  resolved: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
  closed: 'bg-muted/20 text-muted border-muted/40',
};

const RECEIPT_STATE_COLORS: Record<string, string> = {
  created: 'bg-acid-orange/15 text-acid-orange border-acid-orange/30',
  approved: 'bg-[var(--acid-cyan)]/15 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30',
  executed: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/30',
  expired: 'bg-acid-red/15 text-acid-red border-acid-red/30',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${
        STATUS_COLORS[status] || STATUS_COLORS.open
      }`}
    >
      {status.toUpperCase().replace('_', ' ')}
    </span>
  );
}

function ReceiptStateBadge({ state }: { state: string }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${
        RECEIPT_STATE_COLORS[state] || RECEIPT_STATE_COLORS.created
      }`}
    >
      RECEIPT {state.toUpperCase()}
    </span>
  );
}

function PriorityIndicator({ priority }: { priority?: string }) {
  if (!priority) return null;
  const colors: Record<string, string> = {
    critical: 'text-acid-red',
    high: 'text-acid-orange',
    medium: 'text-[var(--acid-yellow)]',
    low: 'text-[var(--acid-cyan)]',
  };
  const icons: Record<string, string> = { critical: '!!!', high: '!!', medium: '!', low: '-' };
  return (
    <span className={`text-xs font-theme-data ${colors[priority] || 'text-muted'}`}>
      {icons[priority] || ''}
    </span>
  );
}

type ActiveView = 'inboxes' | 'messages' | 'rules';

interface ReceiptPayload {
  receipt_id: string;
  state: string;
  review_choice?: string | null;
}

interface SharedInboxDebateResult {
  debate_id?: string;
  final_answer?: string;
  consensus_reached?: boolean;
  confidence?: number;
  receipt_created?: boolean;
  receipt_error?: string | null;
  receipt?: ReceiptPayload | null;
  executed?: boolean;
  execution_result?: Record<string, unknown> | null;
  execution_error?: string | null;
}

export default function SharedInboxPage() {
  const { config: backendConfig } = useBackend();
  const { tokens, organization, user } = useAuth();

  const [inboxes, setInboxes] = useState<SharedInbox[]>([]);
  const [selectedInbox, setSelectedInbox] = useState<SharedInbox | null>(null);
  const [messages, setMessages] = useState<SharedInboxMessage[]>([]);
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState<ActiveView>('inboxes');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showCreateInbox, setShowCreateInbox] = useState(false);
  const [showCreateRule, setShowCreateRule] = useState(false);

  // Form states
  const [newInboxName, setNewInboxName] = useState('');
  const [newInboxDescription, setNewInboxDescription] = useState('');
  const [newInboxEmail, setNewInboxEmail] = useState('');

  // Auto-debate states
  const [debateResults, setDebateResults] = useState<Record<string, SharedInboxDebateResult>>({});
  const [debatingMessageId, setDebatingMessageId] = useState<string | null>(null);
  const [receiptActionMessageId, setReceiptActionMessageId] = useState<string | null>(null);
  // Get workspace ID from auth context (organization or user's org_id)
  const workspaceId = organization?.id || user?.org_id || 'default';

  const fetchInboxes = useCallback(async () => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/inbox/shared?workspace_id=${workspaceId}`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );
      if (response.ok) {
        const data = await response.json();
        setInboxes(data.inboxes || []);
      } else {
        // API error - show empty state (component handles this gracefully)
        setInboxes([]);
        console.error('Failed to fetch inboxes:', response.status);
      }
    } catch (error) {
      // Network error - show empty state
      setInboxes([]);
      console.error('Error fetching inboxes:', error);
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token, workspaceId]);

  const fetchMessages = useCallback(
    async (inboxId: string) => {
      try {
        const params = new URLSearchParams();
        if (statusFilter !== 'all') params.set('status', statusFilter);

        const response = await fetch(
          `${backendConfig.api}/api/v1/inbox/shared/${inboxId}/messages?${params}`,
          { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
        );
        if (response.ok) {
          const data = await response.json();
          setMessages(data.messages || []);
        } else {
          // API error - show empty state (component handles this gracefully)
          setMessages([]);
          console.error('Failed to fetch messages:', response.status);
        }
      } catch (error) {
        // Network error - show empty state
        setMessages([]);
        console.error('Error fetching messages:', error);
      }
    },
    [backendConfig.api, tokens?.access_token, statusFilter],
  );

  const fetchRules = useCallback(async () => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/inbox/routing/rules?workspace_id=${workspaceId}`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );
      if (response.ok) {
        const data = await response.json();
        setRules(data.rules || []);
      } else {
        // API error - show empty state (component handles this gracefully)
        setRules([]);
        console.error('Failed to fetch rules:', response.status);
      }
    } catch (error) {
      // Network error - show empty state
      setRules([]);
      console.error('Error fetching rules:', error);
    }
  }, [backendConfig.api, tokens?.access_token, workspaceId]);

  useEffect(() => {
    fetchInboxes();
    fetchRules();
  }, [fetchInboxes, fetchRules]);

  useEffect(() => {
    if (selectedInbox) {
      fetchMessages(selectedInbox.id);
    }
  }, [selectedInbox, fetchMessages]);

  const handleCreateInbox = async () => {
    if (!newInboxName.trim()) return;

    try {
      const response = await fetch(`${backendConfig.api}/api/v1/inbox/shared`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          name: newInboxName,
          description: newInboxDescription || undefined,
          email_address: newInboxEmail || undefined,
        }),
      });

      if (response.ok) {
        fetchInboxes();
        setShowCreateInbox(false);
        setNewInboxName('');
        setNewInboxDescription('');
        setNewInboxEmail('');
      }
    } catch {
      // Handle error
    }
  };

  const handleAssign = async (messageId: string, assignedTo: string) => {
    if (!selectedInbox) return;

    try {
      await fetch(
        `${backendConfig.api}/api/v1/inbox/shared/${selectedInbox.id}/messages/${messageId}/assign`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({ assigned_to: assignedTo }),
        },
      );
      fetchMessages(selectedInbox.id);
    } catch {
      // Handle error
    }
  };

  const handleStatusChange = async (messageId: string, newStatus: string) => {
    if (!selectedInbox) return;

    try {
      await fetch(
        `${backendConfig.api}/api/v1/inbox/shared/${selectedInbox.id}/messages/${messageId}/status`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({ status: newStatus }),
        },
      );
      fetchMessages(selectedInbox.id);
    } catch {
      // Handle error
    }
  };

  const handleStartDebate = async (messageId: string) => {
    setDebatingMessageId(messageId);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/inbox/messages/${messageId}/debate`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({
            create_receipt: true,
            allowed_actions: ['archive', 'star'],
            auto_approve: false,
            auto_execute: false,
          }),
        },
      );
      if (response.ok) {
        const json = await response.json();
        const result = (json.data || json) as SharedInboxDebateResult;
        setDebateResults((prev) => ({ ...prev, [messageId]: result }));
      } else {
        const json = await response.json().catch(() => ({}));
        setDebateResults((prev) => ({
          ...prev,
          [messageId]: {
            receipt_created: false,
            receipt_error: json.error || 'Failed to stage receipt-backed review.',
          },
        }));
      }
    } catch {
      setDebateResults((prev) => ({
        ...prev,
        [messageId]: {
          receipt_created: false,
          receipt_error: 'Failed to stage receipt-backed review.',
        },
      }));
    } finally {
      setDebatingMessageId(null);
    }
  };

  const handleReceiptReview = async (
    messageId: string,
    choice: 'approve' | 'reject',
    execute = false,
  ) => {
    const receiptId = debateResults[messageId]?.receipt?.receipt_id;
    if (!receiptId) return;

    setReceiptActionMessageId(messageId);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/inbox/wedge/receipts/${receiptId}/review`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({ choice, execute }),
        },
      );

      const json = await response.json().catch(() => ({}));
      if (response.ok) {
        setDebateResults((prev) => ({
          ...prev,
          [messageId]: {
            ...prev[messageId],
            receipt: json.receipt || prev[messageId]?.receipt,
            executed: Boolean(json.executed),
            execution_result: json.execution_result || null,
            execution_error: null,
          },
        }));
      } else {
        setDebateResults((prev) => ({
          ...prev,
          [messageId]: {
            ...prev[messageId],
            execution_error: json.error || 'Receipt review failed.',
          },
        }));
      }
    } catch {
      setDebateResults((prev) => ({
        ...prev,
        [messageId]: { ...prev[messageId], execution_error: 'Receipt review failed.' },
      }));
    } finally {
      setReceiptActionMessageId(null);
    }
  };

  const handleReceiptExecute = async (messageId: string) => {
    const receiptId = debateResults[messageId]?.receipt?.receipt_id;
    if (!receiptId) return;

    setReceiptActionMessageId(messageId);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/inbox/wedge/receipts/${receiptId}/execute`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({}),
        },
      );

      const json = await response.json().catch(() => ({}));
      if (response.ok) {
        setDebateResults((prev) => ({
          ...prev,
          [messageId]: {
            ...prev[messageId],
            receipt: json.receipt || prev[messageId]?.receipt,
            executed: true,
            execution_result: json.execution_result || null,
            execution_error: null,
          },
        }));
      } else {
        setDebateResults((prev) => ({
          ...prev,
          [messageId]: {
            ...prev[messageId],
            execution_error: json.error || 'Receipt execution failed.',
          },
        }));
      }
    } catch {
      setDebateResults((prev) => ({
        ...prev,
        [messageId]: { ...prev[messageId], execution_error: 'Receipt execution failed.' },
      }));
    } finally {
      setReceiptActionMessageId(null);
    }
  };
  const formatDate = (dateStr: string): string => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <div className="min-h-screen bg-background">
      <Scanlines />
      <CRTVignette />

      <header className="border-b border-border bg-surface/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="hover:text-accent">
              <AsciiBannerCompact />
            </Link>
            <span className="text-muted font-theme-data text-sm">{'//'} SHARED INBOX</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/inbox" className="text-xs font-theme-data text-muted hover:text-accent">
              Personal Inbox
            </Link>
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-theme-data mb-1">SHARED INBOX</h1>
            <p className="text-muted text-sm font-theme-data">
              Team collaboration email management
            </p>
          </div>
          <button onClick={() => setShowCreateInbox(true)} className="btn btn-primary">
            + New Inbox
          </button>
        </div>

        {/* View Tabs */}
        <div className="border-b border-border mb-6">
          <div className="flex gap-4">
            {[
              { id: 'inboxes' as ActiveView, label: 'INBOXES', count: inboxes.length },
              { id: 'messages' as ActiveView, label: 'MESSAGES', count: messages.length },
              { id: 'rules' as ActiveView, label: 'ROUTING RULES', count: rules.length },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveView(tab.id)}
                className={`px-4 py-2 font-theme-data text-sm transition-colors flex items-center gap-2 ${
                  activeView === tab.id
                    ? 'text-accent border-b-2 border-accent'
                    : 'text-muted hover:text-foreground'
                }`}
              >
                {tab.label}
                <span className="px-1.5 py-0.5 bg-surface rounded text-xs">{tab.count}</span>
              </button>
            ))}
          </div>
        </div>

        <PanelErrorBoundary panelName="Shared Inbox Content">
          {/* Inboxes View */}
          {activeView === 'inboxes' && (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {loading ? (
                [1, 2, 3].map((i) => (
                  <div key={i} className="card p-4 animate-pulse">
                    <div className="h-6 bg-surface rounded mb-2" />
                    <div className="h-4 bg-surface rounded w-2/3" />
                  </div>
                ))
              ) : inboxes.length === 0 ? (
                <div className="col-span-full card p-12 text-center">
                  <div className="text-4xl mb-4">📬</div>
                  <div className="text-muted font-theme-data mb-4">No shared inboxes yet</div>
                  <button onClick={() => setShowCreateInbox(true)} className="btn btn-primary">
                    Create First Inbox
                  </button>
                </div>
              ) : (
                inboxes.map((inbox) => (
                  <div
                    key={inbox.id}
                    onClick={() => {
                      setSelectedInbox(inbox);
                      setActiveView('messages');
                    }}
                    className={`card p-4 cursor-pointer transition-all hover:border-accent/50 ${
                      selectedInbox?.id === inbox.id ? 'border-accent' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <h3 className="font-theme-data font-medium">{inbox.name}</h3>
                      {inbox.unread_count > 0 && (
                        <span className="px-2 py-0.5 bg-accent/20 text-accent text-xs font-theme-data rounded">
                          {inbox.unread_count} new
                        </span>
                      )}
                    </div>
                    {inbox.description && (
                      <p className="text-sm text-muted mb-3">{inbox.description}</p>
                    )}
                    <div className="flex items-center justify-between text-xs font-theme-data text-muted">
                      <span>{inbox.message_count} messages</span>
                      <span>{inbox.team_members.length} members</span>
                    </div>
                    {inbox.email_address && (
                      <div className="mt-2 text-xs font-theme-data text-accent/70 truncate">
                        {inbox.email_address}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Messages View */}
          {activeView === 'messages' && (
            <div>
              {/* Inbox Selector & Filters */}
              <div className="flex items-center gap-4 mb-4">
                <select
                  value={selectedInbox?.id || ''}
                  onChange={(e) => {
                    const inbox = inboxes.find((i) => i.id === e.target.value);
                    setSelectedInbox(inbox || null);
                  }}
                  className="input"
                >
                  <option value="">Select Inbox...</option>
                  {inboxes.map((inbox) => (
                    <option key={inbox.id} value={inbox.id}>
                      {inbox.name} ({inbox.message_count})
                    </option>
                  ))}
                </select>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="input"
                >
                  <option value="all">All Status</option>
                  <option value="open">Open</option>
                  <option value="assigned">Assigned</option>
                  <option value="in_progress">In Progress</option>
                  <option value="waiting">Waiting</option>
                  <option value="resolved">Resolved</option>
                </select>
              </div>

              {/* Messages List */}
              {!selectedInbox ? (
                <div className="card p-12 text-center">
                  <div className="text-muted font-theme-data">Select an inbox to view messages</div>
                </div>
              ) : messages.length === 0 ? (
                <div className="card p-12 text-center">
                  <div className="text-4xl mb-4">📭</div>
                  <div className="text-muted font-theme-data">No messages in this inbox</div>
                </div>
              ) : (
                <div className="space-y-2">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className="card p-4 hover:border-accent/30 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <PriorityIndicator priority={message.priority} />
                            <span className="font-theme-data text-sm truncate">
                              {message.subject}
                            </span>
                          </div>
                          <div className="text-xs text-muted mb-2">
                            From: {message.from_address}
                          </div>
                          <p className="text-sm text-muted truncate">{message.snippet}</p>
                          <div className="flex items-center gap-2 mt-2">
                            {message.tags.map((tag) => (
                              <span
                                key={tag}
                                className="px-1.5 py-0.5 bg-surface text-xs font-theme-data rounded"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <StatusBadge status={message.status} />
                          {message.trust_wedge?.receipt?.state && (
                            <ReceiptStateBadge state={message.trust_wedge.receipt.state} />
                          )}
                          <span className="text-xs text-muted">
                            {formatDate(message.received_at)}
                          </span>
                          {message.assigned_to && (
                            <span className="text-xs text-accent">@ {message.assigned_to}</span>
                          )}
                        </div>
                      </div>

                      {/* Quick Actions */}
                      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-border">
                        {message.status === 'open' && (
                          <button
                            onClick={() => handleAssign(message.id, 'me')}
                            className="px-2 py-1 text-xs font-theme-data bg-accent/10 text-accent hover:bg-accent/20 rounded transition-colors"
                          >
                            Claim
                          </button>
                        )}
                        {message.status !== 'resolved' && (
                          <button
                            onClick={() => handleStatusChange(message.id, 'resolved')}
                            className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded transition-colors"
                          >
                            Resolve
                          </button>
                        )}
                        <button className="px-2 py-1 text-xs font-theme-data bg-surface hover:bg-accent/10 rounded transition-colors">
                          View
                        </button>
                        <button className="px-2 py-1 text-xs font-theme-data bg-surface hover:bg-accent/10 rounded transition-colors">
                          Reply
                        </button>
                        {(message.priority === 'critical' || message.priority === 'high') &&
                          !debateResults[message.id]?.receipt &&
                          !message.trust_wedge?.receipt && (
                            <button
                              onClick={() => handleStartDebate(message.id)}
                              disabled={debatingMessageId === message.id}
                              className="px-2 py-1 text-xs font-theme-data bg-acid-purple/10 text-acid-purple hover:bg-acid-purple/20 rounded transition-colors disabled:opacity-50"
                            >
                              {debatingMessageId === message.id ? 'Staging...' : 'Stage Review'}
                            </button>
                          )}
                      </div>

                      {message.trust_wedge?.decision?.final_action && (
                        <div className="mt-2 text-xs font-theme-data text-muted">
                          Canonical action:{' '}
                          {message.trust_wedge.decision.final_action.toUpperCase()}
                        </div>
                      )}

                      {/* Debate Result */}
                      {debateResults[message.id] && (
                        <div className="mt-2 p-2 bg-acid-purple/5 border border-acid-purple/20 rounded text-xs font-theme-data">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-acid-purple font-medium">TRUST WEDGE</span>
                            {debateResults[message.id].consensus_reached && (
                              <span className="px-1.5 py-0.5 bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                                CONSENSUS
                              </span>
                            )}
                            {typeof debateResults[message.id].confidence === 'number' && (
                              <span className="text-muted">
                                confidence:{' '}
                                {(debateResults[message.id].confidence! * 100).toFixed(0)}%
                              </span>
                            )}
                            {debateResults[message.id].receipt?.state && (
                              <span className="px-1.5 py-0.5 bg-surface text-accent rounded">
                                {debateResults[message.id].receipt?.state.toUpperCase()}
                              </span>
                            )}
                          </div>
                          {debateResults[message.id].final_answer && (
                            <p className="text-muted">{debateResults[message.id].final_answer}</p>
                          )}
                          {debateResults[message.id].receipt_error && (
                            <p className="text-acid-red mt-1">
                              {debateResults[message.id].receipt_error}
                            </p>
                          )}
                          {debateResults[message.id].execution_error && (
                            <p className="text-acid-red mt-1">
                              {debateResults[message.id].execution_error}
                            </p>
                          )}
                          {debateResults[message.id].receipt?.receipt_id && (
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              {debateResults[message.id].receipt?.state === 'created' && (
                                <>
                                  <button
                                    onClick={() =>
                                      handleReceiptReview(message.id, 'approve', false)
                                    }
                                    disabled={receiptActionMessageId === message.id}
                                    className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded transition-colors disabled:opacity-50"
                                  >
                                    Approve
                                  </button>
                                  <button
                                    onClick={() => handleReceiptReview(message.id, 'approve', true)}
                                    disabled={receiptActionMessageId === message.id}
                                    className="px-2 py-1 text-xs font-theme-data bg-accent/10 text-accent hover:bg-accent/20 rounded transition-colors disabled:opacity-50"
                                  >
                                    Approve + Execute
                                  </button>
                                  <button
                                    onClick={() => handleReceiptReview(message.id, 'reject', false)}
                                    disabled={receiptActionMessageId === message.id}
                                    className="px-2 py-1 text-xs font-theme-data bg-acid-red/10 text-acid-red hover:bg-acid-red/20 rounded transition-colors disabled:opacity-50"
                                  >
                                    Reject
                                  </button>
                                </>
                              )}
                              {debateResults[message.id].receipt?.state === 'approved' &&
                                !debateResults[message.id].executed && (
                                  <button
                                    onClick={() => handleReceiptExecute(message.id)}
                                    disabled={receiptActionMessageId === message.id}
                                    className="px-2 py-1 text-xs font-theme-data bg-accent/10 text-accent hover:bg-accent/20 rounded transition-colors disabled:opacity-50"
                                  >
                                    Execute
                                  </button>
                                )}
                              {debateResults[message.id].executed && (
                                <span className="text-[var(--accent)]">
                                  Action executed with receipt.
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Rules View */}
          {activeView === 'rules' && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm text-muted font-theme-data">
                  {rules.length} routing rule{rules.length !== 1 ? 's' : ''}
                </span>
                <button onClick={() => setShowCreateRule(true)} className="btn btn-sm btn-ghost">
                  + Add Rule
                </button>
              </div>

              {rules.length === 0 ? (
                <div className="card p-12 text-center">
                  <div className="text-4xl mb-4">🔀</div>
                  <div className="text-muted font-theme-data mb-4">No routing rules configured</div>
                  <button onClick={() => setShowCreateRule(true)} className="btn btn-primary">
                    Create First Rule
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {rules.map((rule) => (
                    <div key={rule.id} className={`card p-4 ${!rule.enabled ? 'opacity-50' : ''}`}>
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-theme-data font-medium">{rule.name}</span>
                            <span className="text-xs text-muted">Priority: {rule.priority}</span>
                            {!rule.enabled && (
                              <span className="px-1.5 py-0.5 bg-muted/20 text-muted text-xs rounded">
                                DISABLED
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-muted mb-2">
                            {rule.conditions.map((c, i) => (
                              <span key={i}>
                                {i > 0 && ' AND '}
                                {c.field} {c.operator} "{c.value}"
                              </span>
                            ))}
                          </div>
                          <div className="flex items-center gap-2">
                            {rule.actions.map((a, i) => (
                              <span
                                key={i}
                                className="px-1.5 py-0.5 bg-accent/10 text-accent text-xs font-theme-data rounded"
                              >
                                {a.type}
                                {a.target && `: ${a.target}`}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs text-muted">
                            {rule.stats.total_matches} matches
                          </div>
                          <div className="flex items-center gap-1 mt-2">
                            <button className="px-2 py-1 text-xs font-theme-data bg-surface hover:bg-accent/10 rounded transition-colors">
                              Edit
                            </button>
                            <button className="px-2 py-1 text-xs font-theme-data bg-surface hover:bg-accent/10 rounded transition-colors">
                              Test
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </PanelErrorBoundary>

        {/* Create Inbox Modal */}
        {showCreateInbox && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="card p-6 max-w-md w-full mx-4">
              <h2 className="text-lg font-theme-data mb-4">Create Shared Inbox</h2>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-theme-data text-muted mb-1">Name *</label>
                  <input
                    type="text"
                    value={newInboxName}
                    onChange={(e) => setNewInboxName(e.target.value)}
                    placeholder="Support"
                    className="input w-full"
                  />
                </div>
                <div>
                  <label className="block text-sm font-theme-data text-muted mb-1">
                    Description
                  </label>
                  <input
                    type="text"
                    value={newInboxDescription}
                    onChange={(e) => setNewInboxDescription(e.target.value)}
                    placeholder="Customer support inquiries"
                    className="input w-full"
                  />
                </div>
                <div>
                  <label className="block text-sm font-theme-data text-muted mb-1">
                    Email Address
                  </label>
                  <input
                    type="email"
                    value={newInboxEmail}
                    onChange={(e) => setNewInboxEmail(e.target.value)}
                    placeholder="support@company.com"
                    className="input w-full"
                  />
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 mt-6">
                <button onClick={() => setShowCreateInbox(false)} className="btn btn-ghost">
                  Cancel
                </button>
                <button
                  onClick={handleCreateInbox}
                  disabled={!newInboxName.trim()}
                  className="btn btn-primary"
                >
                  Create
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Create Rule Modal - Placeholder */}
        {showCreateRule && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="card p-6 max-w-lg w-full mx-4">
              <h2 className="text-lg font-theme-data mb-4">Create Routing Rule</h2>
              <p className="text-muted text-sm mb-4">
                Configure conditions and actions for automatic message routing.
              </p>
              <div className="p-4 bg-surface rounded text-center text-muted">
                Rule builder coming soon...
              </div>
              <div className="flex items-center justify-end gap-2 mt-6">
                <button onClick={() => setShowCreateRule(false)} className="btn btn-ghost">
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-border bg-surface/50 py-4 mt-8">
        <div className="container mx-auto px-4 flex items-center justify-between text-xs text-muted font-theme-data">
          <span>ARAGORA SHARED INBOX</span>
          <div className="flex items-center gap-4">
            <Link href="/inbox" className="hover:text-accent">
              PERSONAL
            </Link>
            <Link href="/audit" className="hover:text-accent">
              AUDITS
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
