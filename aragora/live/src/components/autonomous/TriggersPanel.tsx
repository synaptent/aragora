'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface Trigger {
  id: string;
  name: string;
  interval_seconds: number | null;
  cron_expression: string | null;
  enabled: boolean;
  last_run: string | null;
  next_run: string | null;
  run_count: number;
  max_runs: number | null;
  metadata: Record<string, unknown>;
}

interface TriggersPanelProps {
  apiBase: string;
}

export function TriggersPanel({ apiBase }: TriggersPanelProps) {
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newTrigger, setNewTrigger] = useState({
    trigger_id: '',
    name: '',
    interval_minutes: 60,
    topic: '',
    agents: 'anthropic-api,openai-api',
  });

  const fetchTriggers = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await apiFetch<{ triggers: Trigger[] }>(`${apiBase}/autonomous/triggers`);
      if (result.error) {
        throw new Error(result.error);
      }
      setTriggers(result.data?.triggers ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch triggers');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchTriggers();
  }, [fetchTriggers]);

  const handleToggle = async (triggerId: string, enabled: boolean) => {
    try {
      setActionLoading(triggerId);
      await apiFetch(
        `${apiBase}/autonomous/triggers/${triggerId}/${enabled ? 'disable' : 'enable'}`,
        { method: 'POST' },
      );
      await fetchTriggers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to toggle trigger');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (triggerId: string) => {
    if (!confirm('Are you sure you want to delete this trigger?')) return;

    try {
      setActionLoading(triggerId);
      await apiFetch(`${apiBase}/autonomous/triggers/${triggerId}`, { method: 'DELETE' });
      await fetchTriggers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete trigger');
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreate = async () => {
    try {
      setActionLoading('create');
      await apiFetch(`${apiBase}/autonomous/triggers`, {
        method: 'POST',
        body: JSON.stringify({
          trigger_id: newTrigger.trigger_id || `trigger_${Date.now()}`,
          name: newTrigger.name,
          interval_seconds: newTrigger.interval_minutes * 60,
          metadata: {
            topic: newTrigger.topic,
            agents: newTrigger.agents.split(',').map((a) => a.trim()),
          },
        }),
      });
      setShowCreateForm(false);
      setNewTrigger({
        trigger_id: '',
        name: '',
        interval_minutes: 60,
        topic: '',
        agents: 'anthropic-api,openai-api',
      });
      await fetchTriggers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create trigger');
    } finally {
      setActionLoading(null);
    }
  };

  const handleSchedulerAction = async (action: 'start' | 'stop') => {
    try {
      setActionLoading(action);
      await apiFetch(`${apiBase}/autonomous/triggers/${action}`, { method: 'POST' });
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${action} scheduler`);
    } finally {
      setActionLoading(null);
    }
  };

  const formatInterval = (seconds: number | null) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
    return `${Math.round(seconds / 86400)}d`;
  };

  if (loading && triggers.length === 0) {
    return <div className="text-white/50 animate-pulse">Loading triggers...</div>;
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400">
        {error}
        <button onClick={fetchTriggers} className="ml-4 text-sm underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-sm text-white/70">
          {triggers.length} trigger{triggers.length !== 1 ? 's' : ''}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => handleSchedulerAction('start')}
            disabled={actionLoading === 'start'}
            aria-label="Start scheduler"
            className="px-3 py-1.5 text-xs bg-[var(--accent)]/20 hover:bg-[var(--accent)]/30 text-[var(--accent)] rounded"
          >
            {actionLoading === 'start' ? '...' : 'Start Scheduler'}
          </button>
          <button
            onClick={() => handleSchedulerAction('stop')}
            disabled={actionLoading === 'stop'}
            aria-label="Stop scheduler"
            className="px-3 py-1.5 text-xs bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded"
          >
            {actionLoading === 'stop' ? '...' : 'Stop Scheduler'}
          </button>
          <button
            onClick={() => setShowCreateForm(!showCreateForm)}
            aria-expanded={showCreateForm}
            aria-label="Add new trigger"
            className="px-3 py-1.5 text-xs bg-white/10 hover:bg-white/20 text-white rounded"
          >
            + Add Trigger
          </button>
        </div>
      </div>

      {/* Create Form */}
      {showCreateForm && (
        <div
          className="border border-white/10 bg-white/5 rounded-lg p-4 space-y-3"
          role="form"
          aria-label="Create new trigger"
        >
          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="Trigger Name"
              aria-label="Trigger name"
              value={newTrigger.name}
              onChange={(e) => setNewTrigger({ ...newTrigger, name: e.target.value })}
              className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white text-sm"
            />
            <input
              type="number"
              placeholder="Interval (minutes)"
              aria-label="Interval in minutes"
              value={newTrigger.interval_minutes}
              onChange={(e) =>
                setNewTrigger({ ...newTrigger, interval_minutes: parseInt(e.target.value) || 60 })
              }
              className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white text-sm"
            />
            <input
              type="text"
              placeholder="Debate Topic"
              aria-label="Debate topic"
              value={newTrigger.topic}
              onChange={(e) => setNewTrigger({ ...newTrigger, topic: e.target.value })}
              className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white text-sm col-span-2"
            />
            <input
              type="text"
              placeholder="Agents (comma-separated)"
              aria-label="Agent names, comma separated"
              value={newTrigger.agents}
              onChange={(e) => setNewTrigger({ ...newTrigger, agents: e.target.value })}
              className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white text-sm col-span-2"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!newTrigger.name || actionLoading === 'create'}
              className="px-4 py-2 bg-[var(--accent)]/20 hover:bg-[var(--accent)]/30 text-[var(--accent)] rounded text-sm disabled:opacity-50"
            >
              {actionLoading === 'create' ? 'Creating...' : 'Create Trigger'}
            </button>
            <button
              onClick={() => setShowCreateForm(false)}
              className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Triggers List */}
      {triggers.length === 0 ? (
        <div className="text-center py-12 text-white/50">
          <div className="text-4xl mb-2">⏰</div>
          <div>No scheduled triggers</div>
        </div>
      ) : (
        <div className="space-y-2">
          {triggers.map((trigger) => (
            <div
              key={trigger.id}
              className={`border rounded-lg p-4 ${
                trigger.enabled
                  ? 'border-white/10 bg-white/5'
                  : 'border-white/5 bg-white/[0.02] opacity-60'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-white">{trigger.name}</span>
                    <span
                      className={`w-2 h-2 rounded-full ${trigger.enabled ? 'bg-[var(--accent)]' : 'bg-gray-500'}`}
                      aria-hidden="true"
                    />
                    <span className="sr-only">{trigger.enabled ? 'Active' : 'Inactive'}</span>
                  </div>
                  <div className="flex items-center gap-4 mt-1 text-xs text-white/40">
                    <span>Every {formatInterval(trigger.interval_seconds)}</span>
                    <span>
                      Runs: {trigger.run_count}
                      {trigger.max_runs ? `/${trigger.max_runs}` : ''}
                    </span>
                    {trigger.next_run && (
                      <span>Next: {new Date(trigger.next_run).toLocaleString()}</span>
                    )}
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => handleToggle(trigger.id, trigger.enabled)}
                    disabled={actionLoading === trigger.id}
                    aria-label={
                      trigger.enabled
                        ? `Disable trigger ${trigger.name}`
                        : `Enable trigger ${trigger.name}`
                    }
                    className={`px-3 py-1.5 text-xs rounded transition-colors disabled:opacity-50 ${
                      trigger.enabled
                        ? 'bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-500'
                        : 'bg-[var(--accent)]/20 hover:bg-[var(--accent)]/30 text-[var(--accent)]'
                    }`}
                  >
                    {actionLoading === trigger.id ? '...' : trigger.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={() => handleDelete(trigger.id)}
                    disabled={actionLoading === trigger.id}
                    aria-label={`Delete trigger ${trigger.name}`}
                    className="px-3 py-1.5 text-xs bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded transition-colors disabled:opacity-50"
                  >
                    {actionLoading === trigger.id ? '...' : 'Delete'}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default TriggersPanel;
