'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  usePulseScheduler,
  type SchedulerConfig,
  type ScheduledDebate,
} from '@/hooks/usePulseScheduler';

// ============================================================================
// State Badge Component
// ============================================================================

function StateBadge({ state }: { state: string }) {
  const colors: Record<string, { text: string; bg: string }> = {
    running: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/10' },
    paused: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/10' },
    stopped: { text: 'text-acid-red', bg: 'bg-acid-red/10' },
  };
  const color = colors[state] || colors.stopped;

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data uppercase ${color.text} ${color.bg} rounded`}
    >
      {state}
    </span>
  );
}

// ============================================================================
// Metrics Display
// ============================================================================

function MetricsDisplay({
  metrics,
}: {
  metrics: {
    polls_completed: number;
    debates_created: number;
    debates_failed: number;
    duplicates_skipped: number;
    uptime_seconds: number | null;
  };
}) {
  const formatUptime = (seconds: number | null): string => {
    if (seconds === null) return '-';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div className="text-center">
        <div className="text-lg font-theme-data text-[var(--accent)]">
          {metrics.debates_created}
        </div>
        <div className="text-xs font-theme-data text-text-muted">CREATED</div>
      </div>
      <div className="text-center">
        <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
          {metrics.polls_completed}
        </div>
        <div className="text-xs font-theme-data text-text-muted">POLLS</div>
      </div>
      <div className="text-center">
        <div className="text-lg font-theme-data text-[var(--acid-yellow)]">
          {metrics.duplicates_skipped}
        </div>
        <div className="text-xs font-theme-data text-text-muted">DUPES</div>
      </div>
      <div className="text-center">
        <div className="text-lg font-theme-data text-text">
          {formatUptime(metrics.uptime_seconds)}
        </div>
        <div className="text-xs font-theme-data text-text-muted">UPTIME</div>
      </div>
    </div>
  );
}

// ============================================================================
// Config Editor
// ============================================================================

interface ConfigEditorProps {
  config: SchedulerConfig;
  onUpdate: (updates: Partial<SchedulerConfig>) => Promise<boolean>;
  loading: boolean;
}

function ConfigEditor({ config, onUpdate, loading }: ConfigEditorProps) {
  const [localConfig, setLocalConfig] = useState(config);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setLocalConfig(config);
    setDirty(false);
  }, [config]);

  const handleChange = (key: keyof SchedulerConfig, value: unknown) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  const handleSave = async () => {
    const updates: Partial<SchedulerConfig> = {};

    // Only include changed values
    if (localConfig.max_debates_per_hour !== config.max_debates_per_hour) {
      updates.max_debates_per_hour = localConfig.max_debates_per_hour;
    }
    if (localConfig.poll_interval_seconds !== config.poll_interval_seconds) {
      updates.poll_interval_seconds = localConfig.poll_interval_seconds;
    }
    if (localConfig.min_volume_threshold !== config.min_volume_threshold) {
      updates.min_volume_threshold = localConfig.min_volume_threshold;
    }
    if (JSON.stringify(localConfig.platforms) !== JSON.stringify(config.platforms)) {
      updates.platforms = localConfig.platforms;
    }
    if (
      JSON.stringify(localConfig.allowed_categories) !== JSON.stringify(config.allowed_categories)
    ) {
      updates.allowed_categories = localConfig.allowed_categories;
    }

    if (Object.keys(updates).length > 0) {
      const success = await onUpdate(updates);
      if (success) {
        setDirty(false);
      }
    }
  };

  const AVAILABLE_PLATFORMS = ['hackernews', 'reddit', 'twitter'];
  const AVAILABLE_CATEGORIES = ['tech', 'ai', 'science', 'programming', 'business', 'health'];

  return (
    <div className="space-y-4">
      {/* Rate Limit */}
      <div>
        <label
          htmlFor="pulse-debates-per-hour"
          className="block text-xs font-theme-data text-text-muted mb-1"
        >
          Debates per Hour: {localConfig.max_debates_per_hour}
        </label>
        <input
          id="pulse-debates-per-hour"
          type="range"
          min="1"
          max="12"
          value={localConfig.max_debates_per_hour}
          onChange={(e) => handleChange('max_debates_per_hour', parseInt(e.target.value))}
          className="w-full accent-acid-green"
          aria-label={`Debates per hour: ${localConfig.max_debates_per_hour}`}
        />
      </div>

      {/* Poll Interval */}
      <div>
        <label
          htmlFor="pulse-poll-interval"
          className="block text-xs font-theme-data text-text-muted mb-1"
        >
          Poll Interval: {Math.round(localConfig.poll_interval_seconds / 60)}min
        </label>
        <input
          id="pulse-poll-interval"
          type="range"
          min="60"
          max="900"
          step="60"
          value={localConfig.poll_interval_seconds}
          onChange={(e) => handleChange('poll_interval_seconds', parseInt(e.target.value))}
          className="w-full accent-acid-green"
          aria-label={`Poll interval: ${Math.round(localConfig.poll_interval_seconds / 60)} minutes`}
        />
      </div>

      {/* Volume Threshold */}
      <div>
        <label
          htmlFor="pulse-min-volume"
          className="block text-xs font-theme-data text-text-muted mb-1"
        >
          Min Volume: {localConfig.min_volume_threshold}
        </label>
        <input
          id="pulse-min-volume"
          type="range"
          min="10"
          max="500"
          step="10"
          value={localConfig.min_volume_threshold}
          onChange={(e) => handleChange('min_volume_threshold', parseInt(e.target.value))}
          className="w-full accent-acid-green"
          aria-label={`Minimum volume threshold: ${localConfig.min_volume_threshold}`}
        />
      </div>

      {/* Platforms */}
      <div>
        <label className="block text-xs font-theme-data text-text-muted mb-2">Platforms</label>
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_PLATFORMS.map((platform) => (
            <label key={platform} className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={localConfig.platforms.includes(platform)}
                onChange={(e) => {
                  const newPlatforms = e.target.checked
                    ? [...localConfig.platforms, platform]
                    : localConfig.platforms.filter((p) => p !== platform);
                  handleChange('platforms', newPlatforms);
                }}
                className="accent-acid-green"
              />
              <span className="text-xs font-theme-data text-text capitalize">{platform}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Categories */}
      <div>
        <label className="block text-xs font-theme-data text-text-muted mb-2">
          Allowed Categories
        </label>
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_CATEGORIES.map((category) => (
            <label key={category} className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={localConfig.allowed_categories.includes(category)}
                onChange={(e) => {
                  const newCategories = e.target.checked
                    ? [...localConfig.allowed_categories, category]
                    : localConfig.allowed_categories.filter((c) => c !== category);
                  handleChange('allowed_categories', newCategories);
                }}
                className="accent-acid-green"
              />
              <span className="text-xs font-theme-data text-text capitalize">{category}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Save Button */}
      {dirty && (
        <button
          onClick={handleSave}
          disabled={loading}
          className="w-full py-2 bg-[var(--accent)]/10 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-xs hover:bg-[var(--accent)]/20 disabled:opacity-50 transition-colors"
        >
          {loading ? 'SAVING...' : 'SAVE CONFIGURATION'}
        </button>
      )}
    </div>
  );
}

// ============================================================================
// History List
// ============================================================================

function HistoryList({ debates }: { debates: ScheduledDebate[] }) {
  if (debates.length === 0) {
    return (
      <div className="p-4 text-center text-xs font-theme-data text-text-muted">
        No scheduled debates yet
      </div>
    );
  }

  return (
    <div className="space-y-2 max-h-48 overflow-y-auto">
      {debates.map((debate) => (
        <div key={debate.id} className="p-2 bg-surface/50 border border-[var(--accent)]/10">
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="text-xs font-theme-data text-text truncate" title={debate.topic}>
                {debate.topic.slice(0, 60)}...
              </div>
              <div className="flex items-center gap-2 mt-1 text-xs font-theme-data text-text-muted">
                <span className="capitalize">{debate.platform}</span>
                <span>|</span>
                <span>{debate.hours_ago.toFixed(1)}h ago</span>
                {debate.consensus_reached !== null && (
                  <>
                    <span>|</span>
                    <span
                      className={
                        debate.consensus_reached
                          ? 'text-[var(--accent)]'
                          : 'text-[var(--acid-yellow)]'
                      }
                    >
                      {debate.consensus_reached ? 'CONSENSUS' : 'NO CONSENSUS'}
                    </span>
                  </>
                )}
              </div>
            </div>
            {debate.debate_id && (
              <Link
                href={`/debate/${debate.debate_id}`}
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:underline"
              >
                [VIEW]
              </Link>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export function PulseSchedulerControlPanel() {
  const scheduler = usePulseScheduler();
  const [activeTab, setActiveTab] = useState<'status' | 'config' | 'history'>('status');

  // Fetch status on mount
  useEffect(() => {
    scheduler.fetchStatus();
    scheduler.fetchHistory(20);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Start polling when running
  useEffect(() => {
    if (scheduler.isRunning) {
      scheduler.startPolling(30000);
    } else {
      scheduler.stopPolling();
    }
    return () => scheduler.stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduler.isRunning]);

  const handleToggle = async () => {
    if (scheduler.isRunning) {
      await scheduler.pause();
    } else if (scheduler.isPaused) {
      await scheduler.resume();
    } else {
      await scheduler.start();
    }
  };

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} PULSE SCHEDULER
        </span>
        {scheduler.status && <StateBadge state={scheduler.status.state} />}
      </div>

      {/* Quick Controls */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/10 flex items-center gap-2">
        <button
          onClick={handleToggle}
          disabled={scheduler.actionLoading || scheduler.statusLoading}
          className={`flex-1 py-2 font-theme-data text-xs border transition-colors disabled:opacity-50 ${
            scheduler.isRunning
              ? 'border-acid-yellow text-[var(--acid-yellow)] hover:bg-acid-yellow/10'
              : scheduler.isPaused
                ? 'border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10'
                : 'border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10'
          }`}
        >
          {scheduler.isRunning ? 'PAUSE' : scheduler.isPaused ? 'RESUME' : 'START'}
        </button>
        {(scheduler.isRunning || scheduler.isPaused) && (
          <button
            onClick={() => scheduler.stop()}
            disabled={scheduler.actionLoading}
            className="px-4 py-2 font-theme-data text-xs border border-acid-red text-acid-red hover:bg-acid-red/10 transition-colors disabled:opacity-50"
          >
            STOP
          </button>
        )}
        <button
          onClick={() => scheduler.fetchStatus()}
          disabled={scheduler.statusLoading}
          className="px-4 py-2 font-theme-data text-xs text-text-muted hover:text-[var(--accent)] border border-[var(--accent)]/30 hover:border-[var(--accent)]/50 transition-colors disabled:opacity-50"
        >
          {scheduler.statusLoading ? '...' : 'REFRESH'}
        </button>
      </div>

      {/* Error Display */}
      {(scheduler.statusError || scheduler.actionError) && (
        <div className="px-4 py-2 border-b border-acid-red/30">
          <div className="p-2 text-xs font-theme-data text-acid-red bg-acid-red/10 border border-acid-red/30">
            {'>'} {scheduler.statusError || scheduler.actionError}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div
        className="flex border-b border-[var(--accent)]/10"
        role="tablist"
        aria-label="Scheduler panels"
      >
        {(['status', 'config', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`panel-${tab}`}
            id={`tab-${tab}`}
            className={`flex-1 px-4 py-2 text-xs font-theme-data uppercase transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {activeTab === 'status' && (
          <div className="space-y-4" role="tabpanel" id="panel-status" aria-labelledby="tab-status">
            {scheduler.metrics ? (
              <MetricsDisplay metrics={scheduler.metrics} />
            ) : (
              <div className="text-center text-xs font-theme-data text-text-muted py-4">
                {scheduler.statusLoading ? 'Loading...' : 'Scheduler not initialized'}
              </div>
            )}

            {scheduler.status?.store_analytics && (
              <div className="mt-4 p-3 bg-bg/50 border border-[var(--accent)]/20">
                <div className="text-xs font-theme-data text-text-muted mb-2">STORE ANALYTICS</div>
                <div className="grid grid-cols-3 gap-2 text-xs font-theme-data">
                  <div>
                    <span className="text-text-muted">Total: </span>
                    <span className="text-text">
                      {scheduler.status.store_analytics.total_debates}
                    </span>
                  </div>
                  <div>
                    <span className="text-text-muted">Consensus: </span>
                    <span className="text-[var(--accent)]">
                      {Math.round(scheduler.status.store_analytics.consensus_rate * 100)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-text-muted">Avg Conf: </span>
                    <span className="text-[var(--acid-cyan)]">
                      {(scheduler.status.store_analytics.avg_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'config' && scheduler.config && (
          <div role="tabpanel" id="panel-config" aria-labelledby="tab-config">
            <ConfigEditor
              config={scheduler.config}
              onUpdate={scheduler.updateConfig}
              loading={scheduler.actionLoading}
            />
          </div>
        )}

        {activeTab === 'history' && (
          <div
            className="space-y-3"
            role="tabpanel"
            id="panel-history"
            aria-labelledby="tab-history"
          >
            <button
              onClick={() => scheduler.fetchHistory(20)}
              disabled={scheduler.historyLoading}
              className="w-full py-1 text-xs font-theme-data text-text-muted hover:text-[var(--accent)] border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors disabled:opacity-50"
            >
              {scheduler.historyLoading ? 'Loading...' : 'Refresh History'}
            </button>
            <HistoryList debates={scheduler.history} />
            {scheduler.historyTotal > scheduler.history.length && (
              <div className="text-center text-xs font-theme-data text-text-muted">
                Showing {scheduler.history.length} of {scheduler.historyTotal} debates
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
