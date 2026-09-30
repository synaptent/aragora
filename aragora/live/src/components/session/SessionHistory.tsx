'use client';

import { useState } from 'react';
import { useSession, Session } from '@/hooks/useSession';
import { StatusBadge } from '@/components/shared/StatusBadge';

interface SessionHistoryProps {
  className?: string;
}

/**
 * Full session management panel showing all active sessions
 * with ability to revoke individual sessions or all other sessions.
 */
export function SessionHistory({ className = '' }: SessionHistoryProps) {
  const {
    sessions,
    loading,
    error,
    currentSessionId,
    revokeSession,
    revokeAllOtherSessions,
    fetchSessions,
    getLastActivityAge,
    isSessionExpired,
  } = useSession();

  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokingAll, setRevokingAll] = useState(false);
  const [confirmRevokeAll, setConfirmRevokeAll] = useState(false);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const otherSessions = sessions.filter((s) => s.id !== currentSessionId);

  const handleRevokeSession = async (sessionId: string) => {
    setRevoking(sessionId);
    try {
      await revokeSession(sessionId);
    } finally {
      setRevoking(null);
    }
  };

  const handleRevokeAll = async () => {
    if (!confirmRevokeAll) {
      setConfirmRevokeAll(true);
      return;
    }

    setRevokingAll(true);
    try {
      await revokeAllOtherSessions();
      setConfirmRevokeAll(false);
    } finally {
      setRevokingAll(false);
    }
  };

  const cancelRevokeAll = () => {
    setConfirmRevokeAll(false);
  };

  // Parse device icon from device name
  const getDeviceIcon = (deviceName: string): string => {
    const lower = deviceName.toLowerCase();
    if (lower.includes('mobile') || lower.includes('iphone') || lower.includes('android')) {
      return '[MOBILE]';
    }
    if (lower.includes('tablet') || lower.includes('ipad')) {
      return '[TABLET]';
    }
    return '[DESKTOP]';
  };

  // Get browser from device name
  const getBrowserBadge = (
    deviceName: string,
  ): { label: string; variant: 'info' | 'purple' | 'orange' | 'neutral' } => {
    const lower = deviceName.toLowerCase();
    if (lower.includes('chrome')) return { label: 'Chrome', variant: 'info' };
    if (lower.includes('firefox')) return { label: 'Firefox', variant: 'orange' };
    if (lower.includes('safari')) return { label: 'Safari', variant: 'info' };
    if (lower.includes('edge')) return { label: 'Edge', variant: 'info' };
    return { label: 'Unknown', variant: 'neutral' };
  };

  const formatDate = (dateString: string): string => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const renderSessionRow = (session: Session, isCurrent: boolean) => {
    const browser = getBrowserBadge(session.device_name);
    const isExpired = isSessionExpired(session);
    const isRevoking = revoking === session.id;

    return (
      <div
        key={session.id}
        className={`p-4 border-b border-border last:border-b-0 ${
          isCurrent ? 'bg-[var(--accent)]/5' : ''
        }`}
      >
        <div className="flex items-start justify-between gap-4">
          {/* Session Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                {getDeviceIcon(session.device_name)}
              </span>
              <span className="text-sm font-theme-data text-text truncate">
                {session.device_name}
              </span>
              {isCurrent && <StatusBadge label="Current" variant="success" size="sm" />}
              {isExpired && <StatusBadge label="Expired" variant="error" size="sm" />}
            </div>

            <div className="flex items-center gap-3 text-xs font-theme-data text-text-muted mt-2">
              <StatusBadge label={browser.label} variant={browser.variant} size="sm" />
              <span>IP: {session.ip_address}</span>
            </div>

            <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted mt-2">
              <span>Created: {formatDate(session.created_at)}</span>
              <span>Last active: {getLastActivityAge(session)}</span>
            </div>
          </div>

          {/* Actions */}
          {!isCurrent && (
            <button
              onClick={() => handleRevokeSession(session.id)}
              disabled={isRevoking}
              className={`px-3 py-1.5 text-xs font-theme-data border transition-colors focus:outline-none focus:ring-2 focus:ring-warning/50 ${
                isRevoking
                  ? 'bg-warning/10 border-warning/30 text-warning/50 cursor-wait'
                  : 'bg-transparent border-warning/50 text-warning hover:bg-warning/10'
              }`}
            >
              {isRevoking ? '[REVOKING...]' : '[REVOKE]'}
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={`bg-surface border border-border ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div>
          <h3 className="text-sm font-theme-data text-[var(--accent)]">[ACTIVE SESSIONS]</h3>
          <p className="text-xs font-theme-data text-text-muted mt-1">
            Manage your active login sessions across devices
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchSessions}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/10 transition-colors focus:outline-none focus:ring-2 focus:ring-acid-cyan/50"
          >
            {loading ? '[REFRESHING...]' : '[REFRESH]'}
          </button>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="p-4 bg-warning/10 border-b border-warning/30">
          <p className="text-xs font-theme-data text-warning">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loading && sessions.length === 0 && (
        <div className="p-8 text-center">
          <p className="text-sm font-theme-data text-text-muted animate-pulse">
            Loading sessions...
          </p>
        </div>
      )}

      {/* Current Session */}
      {currentSession && (
        <div>
          <div className="px-4 py-2 bg-surface-alt text-xs font-theme-data text-text-muted">
            THIS DEVICE
          </div>
          {renderSessionRow(currentSession, true)}
        </div>
      )}

      {/* Other Sessions */}
      {otherSessions.length > 0 && (
        <div>
          <div className="px-4 py-2 bg-surface-alt text-xs font-theme-data text-text-muted flex items-center justify-between">
            <span>OTHER DEVICES ({otherSessions.length})</span>

            {/* Revoke All Button */}
            {confirmRevokeAll ? (
              <div className="flex items-center gap-2">
                <span className="text-warning">Revoke all?</span>
                <button
                  onClick={handleRevokeAll}
                  disabled={revokingAll}
                  className="px-2 py-0.5 text-xs font-theme-data bg-warning/20 border border-warning/50 text-warning hover:bg-warning/30 transition-colors"
                >
                  {revokingAll ? 'REVOKING...' : 'YES'}
                </button>
                <button
                  onClick={cancelRevokeAll}
                  disabled={revokingAll}
                  className="px-2 py-0.5 text-xs font-theme-data border border-border text-text-muted hover:bg-surface-alt transition-colors"
                >
                  NO
                </button>
              </div>
            ) : (
              <button
                onClick={handleRevokeAll}
                className="text-warning hover:text-warning/80 transition-colors"
              >
                [REVOKE ALL]
              </button>
            )}
          </div>
          {otherSessions.map((session) => renderSessionRow(session, false))}
        </div>
      )}

      {/* Empty State */}
      {sessions.length === 0 && !loading && (
        <div className="p-8 text-center">
          <p className="text-sm font-theme-data text-text-muted">No active sessions found</p>
        </div>
      )}

      {/* Only Current Session */}
      {currentSession && otherSessions.length === 0 && (
        <div className="p-4 text-center border-t border-border">
          <p className="text-xs font-theme-data text-text-muted">
            This is your only active session
          </p>
        </div>
      )}

      {/* Session Info Footer */}
      <div className="p-4 border-t border-border bg-surface-alt">
        <p className="text-xs font-theme-data text-text-muted">
          Sessions expire after 24 hours of inactivity. Revoked sessions require re-authentication.
        </p>
      </div>
    </div>
  );
}
