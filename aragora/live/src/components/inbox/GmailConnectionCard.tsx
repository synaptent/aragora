'use client';

interface GmailStatus {
  connected: boolean;
  configured: boolean;
  email_address?: string;
  indexed_count?: number;
  last_sync?: string;
}

interface GmailConnectionCardProps {
  status: GmailStatus | null;
  loading?: boolean;
  onConnect: () => void;
  onDisconnect?: () => void;
  onSync?: () => void;
  isConnecting?: boolean;
  isSyncing?: boolean;
}

export function GmailConnectionCard({
  status,
  loading,
  onConnect,
  onDisconnect,
  onSync,
  isConnecting,
  isSyncing,
}: GmailConnectionCardProps) {
  if (loading) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
        <h3 className="text-[var(--accent)] font-theme-data text-sm mb-2">Gmail Connection</h3>
        <p className="text-text-muted text-xs">Loading...</p>
      </div>
    );
  }

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
      <h3 className="text-[var(--accent)] font-theme-data text-sm mb-2">Gmail Connection</h3>
      {status?.connected ? (
        <div className="space-y-2">
          <p className="text-text-muted text-xs">{status.email_address}</p>
          <p className="text-text-muted text-xs">{status.indexed_count || 0} messages indexed</p>
          <div className="flex gap-2">
            {onSync && (
              <button
                onClick={onSync}
                disabled={isSyncing}
                className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 disabled:opacity-50"
              >
                {isSyncing ? 'Syncing...' : 'Sync Now'}
              </button>
            )}
            {onDisconnect && (
              <button
                onClick={onDisconnect}
                className="px-3 py-1 text-xs font-theme-data bg-red-500/10 border border-red-500/40 text-red-400 hover:bg-red-500/20"
              >
                Disconnect
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={onConnect}
          disabled={isConnecting}
          className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 disabled:opacity-50"
        >
          {isConnecting ? 'Connecting...' : 'Connect Gmail'}
        </button>
      )}
    </div>
  );
}
