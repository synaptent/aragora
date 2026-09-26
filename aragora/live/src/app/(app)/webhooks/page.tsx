'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  created_at: string;
  last_triggered?: string;
  failure_count: number;
}

interface WebhookEvent {
  id: string;
  webhook_id: string;
  event_type: string;
  status: 'success' | 'failed' | 'pending';
  response_code?: number;
  triggered_at: string;
  request_body?: string;
  response_body?: string;
}

// Events that can trigger webhooks (from WEBHOOK_EVENTS)
const EVENT_TYPES = [
  // Debate lifecycle
  {
    id: 'debate_start',
    label: 'Debate Start',
    description: 'When a new debate begins',
    category: 'Debate',
  },
  {
    id: 'debate_end',
    label: 'Debate End',
    description: 'When a debate concludes',
    category: 'Debate',
  },
  {
    id: 'consensus',
    label: 'Consensus',
    description: 'When agents reach agreement',
    category: 'Debate',
  },
  {
    id: 'round_start',
    label: 'Round Start',
    description: 'When a new round begins',
    category: 'Debate',
  },
  // Agent events
  {
    id: 'agent_message',
    label: 'Agent Message',
    description: 'When an agent sends a message',
    category: 'Agent',
  },
  { id: 'vote', label: 'Vote', description: 'When a vote is recorded', category: 'Agent' },
  // Memory/learning
  {
    id: 'insight_extracted',
    label: 'Insight Extracted',
    description: 'When new insights are learned',
    category: 'Learning',
  },
  // Verification
  {
    id: 'claim_verification_result',
    label: 'Claim Verification',
    description: 'When a claim is verified',
    category: 'Verification',
  },
  {
    id: 'formal_verification_result',
    label: 'Formal Verification',
    description: 'When formal proof completes',
    category: 'Verification',
  },
  // Gauntlet
  {
    id: 'gauntlet_complete',
    label: 'Gauntlet Complete',
    description: 'When gauntlet stress-test finishes',
    category: 'Gauntlet',
  },
  {
    id: 'gauntlet_verdict',
    label: 'Gauntlet Verdict',
    description: 'When verdict is issued',
    category: 'Gauntlet',
  },
  // Graph debates
  {
    id: 'graph_branch_created',
    label: 'Branch Created',
    description: 'When discussion branches',
    category: 'Graph',
  },
  {
    id: 'graph_branch_merged',
    label: 'Branch Merged',
    description: 'When branches merge',
    category: 'Graph',
  },
  // Genesis evolution
  {
    id: 'genesis_evolution',
    label: 'Genesis Evolution',
    description: 'When prompts evolve',
    category: 'Evolution',
  },
  // Breakpoints
  {
    id: 'breakpoint',
    label: 'Breakpoint',
    description: 'Debug breakpoint triggered',
    category: 'Debug',
  },
  {
    id: 'breakpoint_resolved',
    label: 'Breakpoint Resolved',
    description: 'Debug breakpoint resolved',
    category: 'Debug',
  },
];

const EVENT_CATEGORIES = [...new Set(EVENT_TYPES.map((e) => e.category))];

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded ${
        active ? 'bg-[var(--accent)]/20 text-[var(--accent)]' : 'bg-text-muted/20 text-text-muted'
      }`}
    >
      {active ? 'ACTIVE' : 'INACTIVE'}
    </span>
  );
}

function DeliveryStatus({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: 'bg-[var(--accent)]/20 text-[var(--accent)]',
    failed: 'bg-warning/20 text-warning',
    pending: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]',
  };
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded ${colors[status] || colors.pending}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

export default function WebhooksPage() {
  const { config: backendConfig } = useBackend();
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'webhooks' | 'events' | 'create'>('webhooks');

  // Create form state
  const [newUrl, setNewUrl] = useState('');
  const [newName, setNewName] = useState('');
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [_expandedEvent, _setExpandedEvent] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [webhooksRes, eventsRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/webhooks`),
        fetch(`${backendConfig.api}/api/webhooks/events?limit=50`),
      ]);

      if (webhooksRes.ok) {
        const data = await webhooksRes.json();
        setWebhooks(data.webhooks || []);
      }

      if (eventsRes.ok) {
        const data = await eventsRes.json();
        setEvents(data.events || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch webhook data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCreate = async () => {
    if (!newUrl || selectedEvents.length === 0) return;

    setCreating(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/webhooks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: newUrl, events: selectedEvents }),
      });

      if (res.ok) {
        setNewUrl('');
        setSelectedEvents([]);
        setActiveTab('webhooks');
        fetchData();
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to create webhook');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create webhook');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this webhook?')) return;

    try {
      const res = await fetch(`${backendConfig.api}/api/webhooks/${id}`, { method: 'DELETE' });

      if (res.ok) {
        fetchData();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete webhook');
    }
  };

  const handleToggle = async (id: string, active: boolean) => {
    try {
      const res = await fetch(`${backendConfig.api}/api/webhooks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !active }),
      });

      if (res.ok) {
        fetchData();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to toggle webhook');
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    setTestResult(null);

    try {
      const res = await fetch(`${backendConfig.api}/api/webhooks/${id}/test`, { method: 'POST' });

      const data = await res.json();

      if (res.ok) {
        setTestResult({
          success: true,
          message: `Test sent! Response: HTTP ${data.response_status || 200}`,
        });
        fetchData(); // Refresh to show updated delivery log
      } else {
        setTestResult({ success: false, message: data.error || 'Test failed' });
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : 'Test failed',
      });
    } finally {
      setTesting(null);
    }
  };

  const toggleEvent = (eventId: string) => {
    setSelectedEvents((prev) =>
      prev.includes(eventId) ? prev.filter((e) => e !== eventId) : [...prev, eventId],
    );
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">{'>'} WEBHOOKS</h1>
            <p className="text-text-muted font-theme-data text-sm">
              Configure webhooks to receive real-time notifications for debate events. Integrate
              with external systems, Slack, Discord, or custom applications.
            </p>
          </div>

          {error && (
            <div className="mb-6 p-4 border border-warning/30 bg-warning/10 rounded">
              <p className="text-warning font-theme-data text-sm">{error}</p>
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setActiveTab('webhooks')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'webhooks'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [WEBHOOKS] ({webhooks.length})
            </button>
            <button
              onClick={() => setActiveTab('events')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'events'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [DELIVERY LOG]
            </button>
            <button
              onClick={() => setActiveTab('create')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'create'
                  ? 'border-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)]'
                  : 'border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/5'
              }`}
            >
              [+ NEW]
            </button>
          </div>

          <PanelErrorBoundary panelName="Webhooks">
            {loading ? (
              <div className="p-8 text-center">
                <p className="font-theme-data text-text-muted">Loading webhooks...</p>
              </div>
            ) : activeTab === 'webhooks' ? (
              <div className="space-y-4">
                {webhooks.length === 0 ? (
                  <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                    <p className="font-theme-data text-text-muted mb-4">
                      No webhooks configured yet.
                    </p>
                    <button
                      onClick={() => setActiveTab('create')}
                      className="px-4 py-2 border border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)] font-theme-data text-sm hover:bg-[var(--acid-cyan)]/10 transition-colors"
                    >
                      [CREATE WEBHOOK]
                    </button>
                  </div>
                ) : (
                  webhooks.map((webhook) => (
                    <div
                      key={webhook.id}
                      className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <code className="text-[var(--acid-cyan)] text-sm break-all">
                            {webhook.url}
                          </code>
                          <div className="flex items-center gap-2 mt-1">
                            <StatusBadge active={webhook.active} />
                            {webhook.failure_count > 0 && (
                              <span className="text-xs font-theme-data text-warning">
                                {webhook.failure_count} failures
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex gap-2 flex-shrink-0">
                          <button
                            onClick={() => handleTest(webhook.id)}
                            disabled={testing === webhook.id || !webhook.active}
                            className="px-2 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors disabled:opacity-50"
                          >
                            {testing === webhook.id ? '[TESTING...]' : '[TEST]'}
                          </button>
                          <button
                            onClick={() => handleToggle(webhook.id, webhook.active)}
                            className="px-2 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-text transition-colors"
                          >
                            {webhook.active ? '[DISABLE]' : '[ENABLE]'}
                          </button>
                          <button
                            onClick={() => handleDelete(webhook.id)}
                            className="px-2 py-1 text-xs font-theme-data border border-warning/30 text-warning hover:bg-warning/10 transition-colors"
                          >
                            [DELETE]
                          </button>
                        </div>
                      </div>

                      {/* Test result notification */}
                      {testResult && testing === null && (
                        <div
                          className={`mb-3 p-2 text-xs font-theme-data rounded ${
                            testResult.success
                              ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                              : 'bg-warning/10 text-warning'
                          }`}
                        >
                          {testResult.message}
                        </div>
                      )}

                      <div className="flex flex-wrap gap-1">
                        {webhook.events.map((event) => {
                          const eventType = EVENT_TYPES.find((e) => e.id === event);
                          return (
                            <span
                              key={event}
                              className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] rounded"
                            >
                              {eventType?.label || event}
                            </span>
                          );
                        })}
                      </div>
                      {webhook.last_triggered && (
                        <div className="mt-2 text-xs font-theme-data text-text-muted">
                          Last triggered: {new Date(webhook.last_triggered).toLocaleString()}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            ) : activeTab === 'events' ? (
              <div className="space-y-2">
                {events.length === 0 ? (
                  <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                    <p className="font-theme-data text-text-muted">
                      No delivery events recorded yet.
                    </p>
                  </div>
                ) : (
                  events.map((event) => (
                    <div
                      key={event.id}
                      className="p-3 border border-[var(--accent)]/10 rounded bg-surface/20 flex items-center justify-between"
                    >
                      <div className="flex items-center gap-3">
                        <DeliveryStatus status={event.status} />
                        <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                          {event.event_type}
                        </span>
                        {event.response_code && (
                          <span className="font-theme-data text-xs text-text-muted">
                            HTTP {event.response_code}
                          </span>
                        )}
                      </div>
                      <span className="font-theme-data text-xs text-text-muted">
                        {new Date(event.triggered_at).toLocaleString()}
                      </span>
                    </div>
                  ))
                )}
              </div>
            ) : (
              <div className="p-6 border border-[var(--acid-cyan)]/30 rounded bg-surface/30">
                <h3 className="font-theme-data text-[var(--acid-cyan)] mb-4">Create New Webhook</h3>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="block font-theme-data text-sm text-text-muted mb-2">
                      Webhook URL *
                    </label>
                    <input
                      type="url"
                      value={newUrl}
                      onChange={(e) => setNewUrl(e.target.value)}
                      placeholder="https://your-server.com/webhook"
                      className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                    />
                  </div>
                  <div>
                    <label className="block font-theme-data text-sm text-text-muted mb-2">
                      Name (optional)
                    </label>
                    <input
                      type="text"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="My webhook"
                      className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                    />
                  </div>
                </div>

                <div className="mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <label className="font-theme-data text-sm text-text-muted">
                      Events to Subscribe ({selectedEvents.length} selected)
                    </label>
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedEvents(
                          selectedEvents.length === EVENT_TYPES.length
                            ? []
                            : EVENT_TYPES.map((e) => e.id),
                        )
                      }
                      className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--acid-cyan)]/80"
                    >
                      {selectedEvents.length === EVENT_TYPES.length
                        ? '[DESELECT ALL]'
                        : '[SELECT ALL]'}
                    </button>
                  </div>

                  {/* Events grouped by category */}
                  {EVENT_CATEGORIES.map((category) => (
                    <div key={category} className="mb-4">
                      <div className="text-xs font-theme-data text-text-muted mb-2 uppercase">
                        {category}
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {EVENT_TYPES.filter((e) => e.category === category).map((event) => (
                          <button
                            key={event.id}
                            type="button"
                            onClick={() => toggleEvent(event.id)}
                            className={`p-3 border text-left transition-colors ${
                              selectedEvents.includes(event.id)
                                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                                : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                            }`}
                          >
                            <div className="font-theme-data text-sm text-text">{event.label}</div>
                            <div className="font-theme-data text-xs text-text-muted">
                              {event.description}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                <button
                  onClick={handleCreate}
                  disabled={creating || !newUrl || selectedEvents.length === 0}
                  className="px-4 py-2 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)] font-theme-data text-sm hover:bg-[var(--acid-cyan)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {creating ? 'Creating...' : '[CREATE WEBHOOK]'}
                </button>
              </div>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // WEBHOOKS</p>
        </footer>
      </main>
    </>
  );
}
