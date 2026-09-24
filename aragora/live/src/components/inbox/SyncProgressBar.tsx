'use client';

interface SyncStatus {
  job_status: string;
  job_progress: number;
  job_messages_synced: number;
  job_error?: string;
}

interface SyncProgressBarProps {
  syncStatus: SyncStatus;
  indexedCount: number;
  lastSync?: string;
  onSync: () => void;
  onFullSync: () => void;
}

export function SyncProgressBar({
  syncStatus,
  indexedCount,
  lastSync,
  onSync,
  onFullSync,
}: SyncProgressBarProps) {
  const { job_status, job_progress, job_messages_synced, job_error } = syncStatus;
  const isRunning = job_status === 'running' || job_status === 'pending';

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
      <div className="flex justify-between items-center mb-2">
        <h3 className="text-[var(--accent)] font-theme-data text-sm">Sync Status</h3>
        <div className="flex gap-2">
          <button
            onClick={onSync}
            disabled={isRunning}
            className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 disabled:opacity-50"
          >
            Quick Sync
          </button>
          <button
            onClick={onFullSync}
            disabled={isRunning}
            className="px-2 py-1 text-xs font-theme-data bg-acid-purple/10 border border-acid-purple/40 text-acid-purple hover:bg-acid-purple/20 disabled:opacity-50"
          >
            Full Sync
          </button>
        </div>
      </div>

      <div className="flex justify-between text-xs font-theme-data text-text-muted mb-2">
        <span>{job_status.toUpperCase()}</span>
        <span>
          {job_messages_synced} / {indexedCount} messages
        </span>
      </div>

      {isRunning && (
        <div className="h-2 bg-bg rounded overflow-hidden mb-2">
          <div
            className="h-full bg-[var(--accent)] transition-all"
            style={{ width: `${job_progress}%` }}
          />
        </div>
      )}

      {lastSync && (
        <p className="text-text-muted text-xs">Last sync: {new Date(lastSync).toLocaleString()}</p>
      )}

      {job_error && <p className="text-red-400 text-xs mt-2">{job_error}</p>}
    </div>
  );
}
