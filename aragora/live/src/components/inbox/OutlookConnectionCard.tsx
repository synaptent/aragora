'use client';

interface OutlookStatus {
  connected: boolean;
  configured: boolean;
  email_address?: string;
  indexed_count?: number;
  last_sync?: string;
}

interface OutlookConnectionCardProps {
  status: OutlookStatus | null;
  loading?: boolean;
  onConnect: () => void;
  onDisconnect?: () => void;
  onSync?: () => void;
  isConnecting?: boolean;
  isSyncing?: boolean;
}

export function OutlookConnectionCard({
  status,
  loading,
  onConnect,
  onDisconnect,
  onSync,
  isConnecting,
  isSyncing,
}: OutlookConnectionCardProps) {
  if (loading) {
    return (
      <div className="border border-[#0078D4]/30 bg-surface/50 p-4 rounded">
        <h3 className="text-[#0078D4] font-theme-data text-sm mb-2">Outlook Connection</h3>
        <p className="text-text-muted text-xs">Loading...</p>
      </div>
    );
  }

  return (
    <div className="border border-[#0078D4]/30 bg-surface/50 p-4 rounded">
      <div className="flex items-center gap-2 mb-2">
        <svg className="w-4 h-4 text-[#0078D4]" viewBox="0 0 24 24" fill="currentColor">
          <path d="M7.88 12.04q0 .45-.11.87-.1.41-.33.74-.22.33-.58.52-.37.2-.87.2t-.85-.2q-.35-.21-.57-.55-.22-.33-.33-.75-.1-.42-.1-.86t.1-.87q.1-.43.34-.76.22-.34.59-.54.36-.2.87-.2t.86.2q.35.21.57.55.22.34.31.77.1.43.1.88zM24 12v9.38q0 .46-.33.8-.33.32-.8.32H7.13q-.46 0-.8-.33-.32-.33-.32-.8V18H1q-.41 0-.7-.3-.3-.29-.3-.7V7q0-.41.3-.7Q.58 6 1 6h6.13V2.55q0-.44.3-.75.3-.3.7-.3h12.74q.41 0 .7.3.3.3.3.75V11q0 .41-.3.7-.29.3-.7.3H19.8v.8h3.4q.4 0 .7.3.3.3.3.7v.2h-5.6v-.1l-.2-.4V12zm-17.54-.5q0-.93-.26-1.64-.26-.72-.75-1.22-.48-.5-1.18-.76-.69-.27-1.57-.27-.9 0-1.61.26-.7.27-1.2.77-.5.51-.76 1.22-.27.71-.27 1.64 0 .92.27 1.63.26.72.76 1.23.5.51 1.2.78.72.27 1.61.27.88 0 1.57-.27.69-.27 1.18-.78.49-.51.75-1.23.26-.71.26-1.63zm17.14 5.5v-4H7.8v4h15.8z" />
        </svg>
        <h3 className="text-[#0078D4] font-theme-data text-sm">Outlook Connection</h3>
      </div>
      {status?.connected ? (
        <div className="space-y-2">
          <p className="text-text-muted text-xs">{status.email_address}</p>
          <p className="text-text-muted text-xs">{status.indexed_count || 0} messages indexed</p>
          <div className="flex gap-2">
            {onSync && (
              <button
                onClick={onSync}
                disabled={isSyncing}
                className="px-3 py-1 text-xs font-theme-data bg-[#0078D4]/10 border border-[#0078D4]/40 text-[#0078D4] hover:bg-[#0078D4]/20 disabled:opacity-50"
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
          className="px-3 py-1 text-xs font-theme-data bg-[#0078D4]/10 border border-[#0078D4]/40 text-[#0078D4] hover:bg-[#0078D4]/20 disabled:opacity-50"
        >
          {isConnecting ? 'Connecting...' : 'Connect Outlook'}
        </button>
      )}
    </div>
  );
}
