'use client';

import { useState, useEffect } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useRightSidebar } from '@/context/RightSidebarContext';
import {
  useModerationStore,
  VERDICT_STYLES,
  type QueuedItem,
  type SpamVerdict,
} from '@/store/moderationStore';

export default function ModerationPage() {
  const {
    config,
    configLoading,
    configError,
    stats,
    queue,
    queueLoading,
    queueError,
    selectedItem,
    fetchConfig,
    updateConfig,
    fetchStats,
    fetchQueue,
    approveItem,
    rejectItem,
    selectItem,
  } = useModerationStore();

  const { setContext, clearContext } = useRightSidebar();

  // Local state for threshold sliders
  const [blockThreshold, setBlockThreshold] = useState(0.9);
  const [reviewThreshold, setReviewThreshold] = useState(0.7);

  // Fetch data on mount
  useEffect(() => {
    fetchConfig();
    fetchStats();
    fetchQueue();

    // Poll stats every 30 seconds
    const interval = setInterval(() => {
      fetchStats();
    }, 30000);

    return () => clearInterval(interval);
  }, [fetchConfig, fetchStats, fetchQueue]);

  // Sync thresholds when config loads
  useEffect(() => {
    if (config) {
      setBlockThreshold(config.block_threshold);
      setReviewThreshold(config.review_threshold);
    }
  }, [config]);

  // Set up right sidebar
  useEffect(() => {
    setContext({
      title: 'Content Moderation',
      subtitle: 'Spam filtering & review',
      statsContent: stats ? (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Total Checks</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">
              {stats.checks.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Blocked</span>
            <span className="text-sm font-theme-data text-red-400">
              {stats.blocked.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Flagged</span>
            <span className="text-sm font-theme-data text-yellow-400">
              {stats.flagged.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Passed</span>
            <span className="text-sm font-theme-data text-green-400">
              {stats.passed.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Cache Hits</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {stats.cache_hits.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Errors</span>
            <span className="text-sm font-theme-data text-red-400">{stats.errors}</span>
          </div>
        </div>
      ) : (
        <div className="text-xs text-[var(--text-muted)]">Loading stats...</div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <button
            onClick={() => fetchQueue()}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            REFRESH QUEUE
          </button>
          <button
            onClick={() => fetchStats()}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            REFRESH STATS
          </button>
        </div>
      ),
    });

    return () => clearContext();
  }, [stats, setContext, clearContext, fetchQueue, fetchStats]);

  // Handle threshold save
  const handleSaveThresholds = async () => {
    await updateConfig({ block_threshold: blockThreshold, review_threshold: reviewThreshold });
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="max-w-6xl mx-auto px-4 py-8">
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              CONTENT MODERATION
            </h1>
            <p className="text-text-muted text-sm font-theme-data">
              Review flagged content and configure spam filtering thresholds
            </p>
          </div>

          {/* Error Banner */}
          {(configError || queueError) && (
            <div className="mb-6 border border-warning/30 bg-warning/10 p-4">
              <p className="text-warning text-sm font-theme-data">{configError || queueError}</p>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Column: Settings */}
            <div className="lg:col-span-1 space-y-6">
              {/* Threshold Settings */}
              <div className="border border-[var(--accent)]/30 bg-surface/50 p-4">
                <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-4 uppercase tracking-wider">
                  Threshold Settings
                </h2>

                {configLoading ? (
                  <div className="text-xs text-text-muted">Loading...</div>
                ) : (
                  <div className="space-y-6">
                    {/* Block Threshold */}
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <label className="text-xs font-theme-data text-text-muted">
                          Block Threshold
                        </label>
                        <span className="text-sm font-theme-data text-red-400">
                          {blockThreshold.toFixed(2)}
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0.5"
                        max="1"
                        step="0.05"
                        value={blockThreshold}
                        onChange={(e) => setBlockThreshold(parseFloat(e.target.value))}
                        className="w-full h-2 bg-surface rounded appearance-none cursor-pointer accent-red-500"
                      />
                      <p className="text-xs text-text-muted/70 mt-1">
                        Content above this score is automatically blocked
                      </p>
                    </div>

                    {/* Review Threshold */}
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <label className="text-xs font-theme-data text-text-muted">
                          Review Threshold
                        </label>
                        <span className="text-sm font-theme-data text-yellow-400">
                          {reviewThreshold.toFixed(2)}
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0.3"
                        max="0.9"
                        step="0.05"
                        value={reviewThreshold}
                        onChange={(e) => setReviewThreshold(parseFloat(e.target.value))}
                        className="w-full h-2 bg-surface rounded appearance-none cursor-pointer accent-yellow-500"
                      />
                      <p className="text-xs text-text-muted/70 mt-1">
                        Content above this score is flagged for manual review
                      </p>
                    </div>

                    {/* Save Button */}
                    <button
                      onClick={handleSaveThresholds}
                      disabled={configLoading}
                      className="w-full py-2 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
                    >
                      SAVE THRESHOLDS
                    </button>
                  </div>
                )}
              </div>

              {/* Quick Stats */}
              {stats && (
                <div className="border border-[var(--acid-cyan)]/30 bg-surface/50 p-4">
                  <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-4 uppercase tracking-wider">
                    Statistics
                  </h2>
                  <div className="grid grid-cols-2 gap-3">
                    <StatBox label="Checks" value={stats.checks} color="text-[var(--accent)]" />
                    <StatBox label="Blocked" value={stats.blocked} color="text-red-400" />
                    <StatBox label="Flagged" value={stats.flagged} color="text-yellow-400" />
                    <StatBox label="Passed" value={stats.passed} color="text-green-400" />
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Review Queue */}
            <div className="lg:col-span-2">
              <div className="border border-[var(--accent)]/30 bg-surface/50">
                {/* Queue Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--accent)]/20">
                  <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
                    Review Queue ({queue.length})
                  </h2>
                  <button
                    onClick={() => fetchQueue()}
                    disabled={queueLoading}
                    className="text-xs font-theme-data text-[var(--accent)] hover:text-[var(--accent)]/80 disabled:opacity-50"
                  >
                    {queueLoading ? 'Loading...' : 'Refresh'}
                  </button>
                </div>

                {/* Queue Content */}
                <div className="max-h-[600px] overflow-y-auto">
                  {queueLoading && queue.length === 0 ? (
                    <div className="p-8 text-center">
                      <div className="w-8 h-8 border-2 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin mx-auto mb-4" />
                      <p className="text-text-muted text-sm font-theme-data">Loading queue...</p>
                    </div>
                  ) : queue.length === 0 ? (
                    <div className="p-8 text-center">
                      <div className="text-4xl mb-4">✅</div>
                      <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">
                        Queue Empty
                      </h3>
                      <p className="text-text-muted text-sm font-theme-data">
                        No content pending review. All clear!
                      </p>
                    </div>
                  ) : (
                    <div className="divide-y divide-acid-green/10">
                      {queue.map((item) => (
                        <QueueItem
                          key={item.id}
                          item={item}
                          isSelected={selectedItem?.id === item.id}
                          onSelect={() => selectItem(selectedItem?.id === item.id ? null : item)}
                          onApprove={() => approveItem(item.id)}
                          onReject={() => rejectItem(item.id)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Selected Item Detail */}
              {selectedItem && (
                <div className="mt-4 border border-[var(--acid-cyan)]/30 bg-surface/50 p-4">
                  <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">
                    Content Details
                  </h3>
                  <div className="space-y-3">
                    {/* Full Content */}
                    <div>
                      <label className="text-xs text-text-muted">Full Content</label>
                      <pre className="mt-1 p-3 bg-bg/50 border border-[var(--accent)]/10 text-xs font-theme-data text-text whitespace-pre-wrap max-h-40 overflow-y-auto">
                        {selectedItem.content}
                      </pre>
                    </div>

                    {/* Score Breakdown */}
                    <div>
                      <label className="text-xs text-text-muted">Score Breakdown</label>
                      <div className="mt-1 grid grid-cols-4 gap-2">
                        <ScoreBar label="Content" value={selectedItem.result.scores.content} />
                        <ScoreBar label="Sender" value={selectedItem.result.scores.sender} />
                        <ScoreBar label="Pattern" value={selectedItem.result.scores.pattern} />
                        <ScoreBar label="URL" value={selectedItem.result.scores.url} />
                      </div>
                    </div>

                    {/* Reasons */}
                    {selectedItem.result.reasons.length > 0 && (
                      <div>
                        <label className="text-xs text-text-muted">Detection Reasons</label>
                        <ul className="mt-1 space-y-1">
                          {selectedItem.result.reasons.map((reason, i) => (
                            <li key={i} className="text-xs font-theme-data text-text-muted/80">
                              • {reason}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

// ============================================================================
// Helper Components
// ============================================================================

function StatBox({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-bg/50 border border-[var(--accent)]/10 p-3 text-center">
      <div className={`text-lg font-theme-data ${color}`}>{value.toLocaleString()}</div>
      <div className="text-xs text-text-muted">{label}</div>
    </div>
  );
}

function QueueItem({
  item,
  isSelected,
  onSelect,
  onApprove,
  onReject,
}: {
  item: QueuedItem;
  isSelected: boolean;
  onSelect: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const style = VERDICT_STYLES[item.result.verdict as SpamVerdict];

  return (
    <div
      className={`p-4 cursor-pointer transition-colors ${
        isSelected ? 'bg-[var(--accent)]/10' : 'hover:bg-surface/80'
      }`}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          {/* Verdict Badge */}
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`px-2 py-0.5 text-xs font-theme-data ${style.color} ${style.bgColor} border border-current/30`}
            >
              {style.label}
            </span>
            <span className="text-xs text-text-muted font-theme-data">
              Score: {(item.result.spam_score * 100).toFixed(0)}%
            </span>
          </div>

          {/* Content Preview */}
          <p className="text-sm font-theme-data text-text truncate">{item.content}</p>

          {/* Meta */}
          <div className="flex items-center gap-4 mt-2 text-xs text-text-muted font-theme-data">
            {item.context?.sender && <span>From: {item.context.sender}</span>}
            <span>Queued: {new Date(item.queued_at).toLocaleString()}</span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={onApprove}
            className="px-3 py-1 text-xs font-theme-data bg-green-500/10 text-green-400 border border-green-500/30 hover:bg-green-500/20 transition-colors"
          >
            APPROVE
          </button>
          <button
            onClick={onReject}
            className="px-3 py-1 text-xs font-theme-data bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors"
          >
            REJECT
          </button>
        </div>
      </div>
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const percentage = Math.round(value * 100);
  const color =
    percentage >= 70 ? 'bg-red-500' : percentage >= 40 ? 'bg-yellow-500' : 'bg-green-500';

  return (
    <div>
      <div className="flex justify-between text-xs text-text-muted mb-1">
        <span>{label}</span>
        <span>{percentage}%</span>
      </div>
      <div className="h-2 bg-surface rounded overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}
