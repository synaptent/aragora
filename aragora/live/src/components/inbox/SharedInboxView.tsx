'use client';

import { useState, useEffect, useCallback } from 'react';
import { TriageRulesPanel } from './TriageRulesPanel';

// Message status types
type MessageStatus = 'open' | 'assigned' | 'in_progress' | 'waiting' | 'resolved' | 'closed';

interface SharedInboxMessage {
  id: string;
  inbox_id: string;
  email_id: string;
  subject: string;
  from_address: string;
  to_addresses: string[];
  snippet: string;
  received_at: string;
  status: MessageStatus;
  assigned_to?: string;
  assigned_at?: string;
  tags: string[];
  priority?: string;
  notes: Array<{ text: string; author: string; created_at: string }>;
  thread_id?: string;
  sla_deadline?: string;
  resolved_at?: string;
  resolved_by?: string;
}

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
}

interface TeamMember {
  id: string;
  name: string;
  email: string;
  avatar?: string;
}

interface SharedInboxViewProps {
  apiBase: string;
  workspaceId: string;
  authToken?: string;
  currentUserId?: string;
  teamMembers?: TeamMember[];
}

const STATUS_CONFIG: Record<MessageStatus, { color: string; label: string; icon: string }> = {
  open: { color: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30', label: 'Open', icon: '⚪' },
  assigned: { color: 'text-blue-400 bg-blue-500/10 border-blue-500/30', label: 'Assigned', icon: '👤' },
  in_progress: { color: 'text-purple-400 bg-purple-500/10 border-purple-500/30', label: 'In Progress', icon: '🔄' },
  waiting: { color: 'text-orange-400 bg-orange-500/10 border-orange-500/30', label: 'Waiting', icon: '⏳' },
  resolved: { color: 'text-green-400 bg-green-500/10 border-green-500/30', label: 'Resolved', icon: '✓' },
  closed: { color: 'text-gray-400 bg-gray-500/10 border-gray-500/30', label: 'Closed', icon: '✗' },
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'text-red-400 bg-red-500/10',
  high: 'text-orange-400 bg-orange-500/10',
  medium: 'text-yellow-400 bg-yellow-500/10',
  low: 'text-blue-400 bg-blue-500/10',
};


export function SharedInboxView({
  apiBase,
  workspaceId,
  authToken,
  currentUserId = 'user1',
  teamMembers = [],
}: SharedInboxViewProps) {
  const [inboxes, setInboxes] = useState<SharedInbox[]>([]);
  const [selectedInbox, setSelectedInbox] = useState<SharedInbox | null>(null);
  const [messages, setMessages] = useState<SharedInboxMessage[]>([]);
  const [selectedMessage, setSelectedMessage] = useState<SharedInboxMessage | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<MessageStatus | 'all'>('all');
  const [assigneeFilter, setAssigneeFilter] = useState<string>('all');
  const [showRulesPanel, setShowRulesPanel] = useState(false);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [emailDetailOpen, setEmailDetailOpen] = useState(false);

  const fetchInboxes = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${apiBase}/api/v1/inbox/shared?workspace_id=${workspaceId}`,
        {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        }
      );

      if (!response.ok) {
        setError(`Failed to load inboxes: ${response.status} ${response.statusText}`);
        setInboxes([]);
        return;
      }

      const data = await response.json();
      const fetchedInboxes = data.inboxes || [];
      setInboxes(fetchedInboxes);
      if (fetchedInboxes.length > 0) {
        setSelectedInbox(fetchedInboxes[0]);
      }
    } catch (err) {
      setError(`Failed to connect to inbox service: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setInboxes([]);
    } finally {
      setIsLoading(false);
    }
  }, [apiBase, workspaceId, authToken]);

  const fetchMessages = useCallback(async () => {
    if (!selectedInbox) return;

    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') {
        params.append('status', statusFilter);
      }
      if (assigneeFilter !== 'all') {
        params.append('assigned_to', assigneeFilter);
      }

      const response = await fetch(
        `${apiBase}/api/v1/inbox/shared/${selectedInbox.id}/messages?${params}`,
        {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        }
      );

      if (!response.ok) {
        setError(`Failed to load messages: ${response.status} ${response.statusText}`);
        setMessages([]);
        return;
      }

      const data = await response.json();
      setMessages(data.messages || []);
      setError(null);
    } catch (err) {
      setError(`Failed to fetch messages: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setMessages([]);
    }
  }, [apiBase, authToken, selectedInbox, statusFilter, assigneeFilter]);

  useEffect(() => {
    fetchInboxes();
  }, [fetchInboxes]);

  useEffect(() => {
    if (selectedInbox) {
      fetchMessages();
    }
  }, [selectedInbox, fetchMessages]);

  const handleAssign = async (messageId: string, userId: string) => {
    try {
      const response = await fetch(
        `${apiBase}/api/v1/inbox/shared/${selectedInbox?.id}/messages/${messageId}/assign`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify({ assigned_to: userId }),
        }
      );

      if (!response.ok) {
        setError(`Failed to assign message: ${response.status} ${response.statusText}`);
        return;
      }

      await fetchMessages();
      setAssignModalOpen(false);
    } catch (error) {
      console.error('Assign failed:', error);
      setError(`Failed to assign message: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const handleStatusChange = async (messageId: string, status: MessageStatus) => {
    try {
      const response = await fetch(
        `${apiBase}/api/v1/inbox/shared/${selectedInbox?.id}/messages/${messageId}/status`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify({ status }),
        }
      );

      if (!response.ok) {
        setError(`Failed to update status: ${response.status} ${response.statusText}`);
        return;
      }

      await fetchMessages();
    } catch (error) {
      console.error('Status change failed:', error);
      setError(`Failed to update status: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const formatTimeAgo = (dateString: string): string => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getTeamMemberName = (userId: string): string => {
    const member = teamMembers.find(m => m.id === userId);
    return member?.name || userId;
  };

  const filteredMessages = messages.filter(m => {
    if (statusFilter !== 'all' && m.status !== statusFilter) return false;
    if (assigneeFilter !== 'all' && m.assigned_to !== assigneeFilter) return false;
    return true;
  });

  const statusCounts = messages.reduce((acc, m) => {
    acc[m.status] = (acc[m.status] || 0) + 1;
    return acc;
  }, {} as Record<MessageStatus, number>);

  if (isLoading) {
    return (
      <div className="border border-acid-green/30 bg-surface/50 p-4 rounded">
        <div className="text-center py-8 text-text-muted font-mono text-sm animate-pulse">
          Loading shared inbox...
        </div>
      </div>
    );
  }

  if (error && inboxes.length === 0) {
    return (
      <div className="border border-red-500/30 bg-red-900/10 p-4 rounded">
        <div className="text-center py-8">
          <div className="text-red-400 font-mono text-sm mb-2">Failed to load inbox</div>
          <div className="text-text-muted text-xs">{error}</div>
          <button
            onClick={() => fetchInboxes()}
            className="mt-4 px-4 py-2 text-xs font-mono border border-acid-green/30 text-acid-green hover:bg-acid-green/10 rounded"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-acid-green/30 p-4 bg-surface/50">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            {/* Inbox Selector */}
            <select
              value={selectedInbox?.id || ''}
              onChange={(e) => {
                const inbox = inboxes.find(i => i.id === e.target.value);
                setSelectedInbox(inbox || null);
              }}
              className="px-3 py-2 text-sm bg-bg border border-acid-green/30 rounded font-mono focus:border-acid-green focus:outline-none"
            >
              {inboxes.map(inbox => (
                <option key={inbox.id} value={inbox.id}>
                  {inbox.name} ({inbox.unread_count} unread)
                </option>
              ))}
            </select>

            {selectedInbox && (
              <div className="text-text-muted text-sm">
                {selectedInbox.email_address && (
                  <span className="font-mono">{selectedInbox.email_address}</span>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowRulesPanel(!showRulesPanel)}
              className={`px-3 py-2 text-xs font-mono border rounded transition-colors ${
                showRulesPanel
                  ? 'bg-acid-green/20 border-acid-green text-acid-green'
                  : 'border-acid-green/30 text-text-muted hover:text-acid-green'
              }`}
            >
              Rules
            </button>
            <button
              onClick={() => fetchMessages()}
              className="px-3 py-2 text-xs font-mono border border-acid-green/30 text-text-muted hover:text-acid-green rounded"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Status Filter Tabs */}
        <div className="flex flex-wrap gap-2 mb-3">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1 text-xs font-mono rounded ${
              statusFilter === 'all'
                ? 'bg-acid-green/20 border border-acid-green text-acid-green'
                : 'bg-surface border border-acid-green/30 text-text-muted hover:text-acid-green'
            }`}
          >
            All ({messages.length})
          </button>
          {(['open', 'assigned', 'in_progress', 'waiting', 'resolved', 'closed'] as MessageStatus[]).map(status => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1 text-xs font-mono rounded flex items-center gap-1 ${
                statusFilter === status
                  ? STATUS_CONFIG[status].color + ' border'
                  : 'bg-surface border border-acid-green/30 text-text-muted hover:text-acid-green'
              }`}
            >
              <span>{STATUS_CONFIG[status].icon}</span>
              <span>{statusCounts[status] || 0}</span>
            </button>
          ))}
        </div>

        {/* Assignee Filter */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Assigned to:</span>
          <select
            value={assigneeFilter}
            onChange={(e) => setAssigneeFilter(e.target.value)}
            className="px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
          >
            <option value="all">Anyone</option>
            <option value={currentUserId}>Me</option>
            {teamMembers.map(member => (
              <option key={member.id} value={member.id}>{member.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Message List */}
        <div className={`${showRulesPanel ? 'w-1/2' : 'w-full'} overflow-y-auto border-r border-acid-green/30`}>
          {filteredMessages.length === 0 ? (
            <div className="text-center py-8 text-text-muted font-mono text-sm">
              No messages match your filters.
            </div>
          ) : (
            <div className="divide-y divide-acid-green/20">
              {filteredMessages.map(message => {
                const statusConfig = STATUS_CONFIG[message.status];
                const isSelected = selectedMessage?.id === message.id;

                return (
                  <div
                    key={message.id}
                    onClick={() => setSelectedMessage(isSelected ? null : message)}
                    className={`p-4 cursor-pointer transition-colors ${
                      isSelected ? 'bg-acid-green/10' : 'hover:bg-bg/50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          {message.priority && (
                            <span className={`px-1.5 py-0.5 text-xs rounded ${PRIORITY_COLORS[message.priority] || ''}`}>
                              {message.priority}
                            </span>
                          )}
                          <span className={`px-1.5 py-0.5 text-xs rounded border ${statusConfig.color}`}>
                            {statusConfig.icon} {statusConfig.label}
                          </span>
                        </div>
                        <h4 className="text-sm font-mono text-text truncate">
                          {message.subject}
                        </h4>
                        <div className="text-xs text-text-muted mt-1">
                          From: {message.from_address}
                        </div>
                        <p className="text-xs text-text-muted mt-1 truncate">
                          {message.snippet}
                        </p>
                        {message.tags.length > 0 && (
                          <div className="flex gap-1 mt-2">
                            {message.tags.map(tag => (
                              <span
                                key={tag}
                                className="px-1.5 py-0.5 text-xs bg-acid-cyan/10 text-acid-cyan rounded"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="text-right text-xs text-text-muted flex-shrink-0">
                        <div>{formatTimeAgo(message.received_at)}</div>
                        {message.assigned_to && (
                          <div className="mt-1 text-acid-green">
                            {getTeamMemberName(message.assigned_to)}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Expanded View */}
                    {isSelected && (
                      <div className="mt-4 pt-4 border-t border-acid-green/20">
                        {/* Actions */}
                        <div className="flex flex-wrap gap-2 mb-4">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setAssignModalOpen(true);
                            }}
                            className="px-3 py-1 text-xs font-mono bg-blue-500/10 border border-blue-500/30 text-blue-400 hover:bg-blue-500/20 rounded"
                          >
                            Assign
                          </button>
                          {message.status !== 'resolved' && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleStatusChange(message.id, 'resolved');
                              }}
                              className="px-3 py-1 text-xs font-mono bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 rounded"
                            >
                              Resolve
                            </button>
                          )}
                          <select
                            value={message.status}
                            onChange={(e) => {
                              e.stopPropagation();
                              handleStatusChange(message.id, e.target.value as MessageStatus);
                            }}
                            onClick={(e) => e.stopPropagation()}
                            className="px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
                          >
                            {(['open', 'assigned', 'in_progress', 'waiting', 'resolved', 'closed'] as MessageStatus[]).map(s => (
                              <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>
                            ))}
                          </select>
                        </div>

                        {/* Notes */}
                        {message.notes.length > 0 && (
                          <div className="mb-4">
                            <span className="text-xs text-text-muted font-mono block mb-2">Notes:</span>
                            <div className="space-y-2">
                              {message.notes.map((note, idx) => (
                                <div key={idx} className="p-2 bg-bg/50 rounded text-xs">
                                  <p className="text-text">{note.text}</p>
                                  <div className="text-text-muted mt-1">
                                    {getTeamMemberName(note.author)} - {formatTimeAgo(note.created_at)}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* View Full Email */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setEmailDetailOpen(true);
                          }}
                          className="px-4 py-2 text-xs font-mono bg-acid-green text-bg hover:bg-acid-green/80 rounded"
                        >
                          View Full Email
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Rules Panel */}
        {showRulesPanel && (
          <div className="w-1/2 overflow-y-auto p-4">
            <TriageRulesPanel
              apiBase={apiBase}
              workspaceId={workspaceId}
              authToken={authToken}
            />
          </div>
        )}
      </div>

      {/* Assign Modal */}
      {assignModalOpen && selectedMessage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setAssignModalOpen(false)}
          />
          <div className="relative w-full max-w-sm mx-4 bg-bg border border-border rounded-lg shadow-xl p-4">
            <h3 className="text-acid-green font-mono text-sm mb-4">Assign Message</h3>
            <div className="space-y-2">
              {teamMembers.map(member => (
                <button
                  key={member.id}
                  onClick={() => handleAssign(selectedMessage.id, member.id)}
                  className={`w-full p-3 text-left rounded border transition-colors ${
                    selectedMessage.assigned_to === member.id
                      ? 'bg-acid-green/20 border-acid-green'
                      : 'border-acid-green/30 hover:border-acid-green/50'
                  }`}
                >
                  <div className="font-mono text-sm">{member.name}</div>
                  <div className="text-xs text-text-muted">{member.email}</div>
                </button>
              ))}
            </div>
            <button
              onClick={() => setAssignModalOpen(false)}
              className="mt-4 w-full px-4 py-2 text-xs font-mono border border-acid-green/30 text-text-muted hover:text-white rounded"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Email Detail Modal */}
      {emailDetailOpen && selectedMessage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setEmailDetailOpen(false)}
          />
          <div className="relative w-full max-w-2xl mx-4 bg-bg border border-border rounded-lg shadow-xl max-h-[80vh] flex flex-col">
            {/* Header */}
            <div className="p-4 border-b border-acid-green/30 flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  {selectedMessage.priority && (
                    <span className={`px-1.5 py-0.5 text-xs rounded ${PRIORITY_COLORS[selectedMessage.priority] || ''}`}>
                      {selectedMessage.priority}
                    </span>
                  )}
                  <span className={`px-1.5 py-0.5 text-xs rounded border ${STATUS_CONFIG[selectedMessage.status].color}`}>
                    {STATUS_CONFIG[selectedMessage.status].icon} {STATUS_CONFIG[selectedMessage.status].label}
                  </span>
                </div>
                <h2 className="text-lg font-mono text-text">{selectedMessage.subject}</h2>
              </div>
              <button
                onClick={() => setEmailDetailOpen(false)}
                className="ml-4 p-1 text-text-muted hover:text-text"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Email Metadata */}
            <div className="p-4 border-b border-acid-green/20 text-sm">
              <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 font-mono">
                <span className="text-text-muted">From:</span>
                <span className="text-text">{selectedMessage.from_address}</span>
                <span className="text-text-muted">To:</span>
                <span className="text-text">{selectedMessage.to_addresses.join(', ')}</span>
                <span className="text-text-muted">Date:</span>
                <span className="text-text">{new Date(selectedMessage.received_at).toLocaleString()}</span>
                {selectedMessage.assigned_to && (
                  <>
                    <span className="text-text-muted">Assigned:</span>
                    <span className="text-acid-green">{getTeamMemberName(selectedMessage.assigned_to)}</span>
                  </>
                )}
              </div>
              {selectedMessage.tags.length > 0 && (
                <div className="flex gap-1 mt-3">
                  {selectedMessage.tags.map(tag => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 text-xs bg-acid-cyan/10 text-acid-cyan rounded"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Email Body */}
            <div className="p-4 flex-1 overflow-y-auto">
              <div className="text-sm text-text whitespace-pre-wrap font-mono">
                {selectedMessage.snippet}
              </div>
            </div>

            {/* Footer Actions */}
            <div className="p-4 border-t border-acid-green/30 flex justify-end gap-2">
              <button
                onClick={() => {
                  setEmailDetailOpen(false);
                  setAssignModalOpen(true);
                }}
                className="px-4 py-2 text-xs font-mono bg-blue-500/10 border border-blue-500/30 text-blue-400 hover:bg-blue-500/20 rounded"
              >
                Assign
              </button>
              {selectedMessage.status !== 'resolved' && (
                <button
                  onClick={() => {
                    handleStatusChange(selectedMessage.id, 'resolved');
                    setEmailDetailOpen(false);
                  }}
                  className="px-4 py-2 text-xs font-mono bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 rounded"
                >
                  Resolve
                </button>
              )}
              <button
                onClick={() => setEmailDetailOpen(false)}
                className="px-4 py-2 text-xs font-mono border border-acid-green/30 text-text-muted hover:text-white rounded"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default SharedInboxView;
