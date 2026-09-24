'use client';

import { useState, useCallback } from 'react';
import { useBlocklist, type BlockedSender } from '@/hooks/useBlocklist';

interface BlocklistPanelProps {
  apiBase: string;
  userId: string;
  authToken?: string;
  onBlockSender?: (sender: string) => void;
}

/**
 * Panel for managing blocked email senders.
 * Blocked senders are filtered out during Tier 1 prioritization with priority=BLOCKED.
 */
export function BlocklistPanel({ apiBase, userId, authToken, onBlockSender }: BlocklistPanelProps) {
  const { blockedSenders, isLoading, error, blockSender, unblockSender, clearError } = useBlocklist(
    { apiBase, userId, authToken },
  );

  const [newSender, setNewSender] = useState('');
  const [newReason, setNewReason] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const handleBlock = useCallback(async () => {
    if (!newSender.trim()) return;

    setActionInProgress('add');
    const success = await blockSender(newSender.trim(), newReason.trim() || 'User blocked');

    if (success) {
      setNewSender('');
      setNewReason('');
      setShowAddForm(false);
      onBlockSender?.(newSender.trim());
    }
    setActionInProgress(null);
  }, [newSender, newReason, blockSender, onBlockSender]);

  const handleUnblock = useCallback(
    async (sender: string) => {
      setActionInProgress(sender);
      await unblockSender(sender);
      setActionInProgress(null);
    },
    [unblockSender],
  );

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[var(--accent)] font-theme-data text-sm">{'>'} BLOCKED SENDERS</h3>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
            showAddForm
              ? 'bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)]'
              : 'bg-surface border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10'
          }`}
        >
          {showAddForm ? 'Cancel' : '+ Block'}
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <div className="mb-4 p-2 bg-red-500/10 border border-red-500/30 rounded flex items-center justify-between">
          <span className="text-red-400 text-xs font-theme-data">{error}</span>
          <button onClick={clearError} className="text-red-400 hover:text-red-300 text-xs">
            [X]
          </button>
        </div>
      )}

      {/* Add Form */}
      {showAddForm && (
        <div className="mb-4 p-3 bg-bg/50 border border-[var(--accent)]/20 rounded space-y-3">
          <div>
            <label className="text-text-muted text-xs font-theme-data block mb-1">
              Email Address or Domain
            </label>
            <input
              type="text"
              value={newSender}
              onChange={(e) => setNewSender(e.target.value)}
              placeholder="spam@example.com or @spam-domain.com"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm rounded focus:outline-none focus:border-[var(--accent)]"
              disabled={actionInProgress === 'add'}
            />
          </div>
          <div>
            <label className="text-text-muted text-xs font-theme-data block mb-1">
              Reason (optional)
            </label>
            <input
              type="text"
              value={newReason}
              onChange={(e) => setNewReason(e.target.value)}
              placeholder="Spam, unwanted marketing, etc."
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm rounded focus:outline-none focus:border-[var(--accent)]"
              disabled={actionInProgress === 'add'}
            />
          </div>
          <button
            onClick={handleBlock}
            disabled={!newSender.trim() || actionInProgress === 'add'}
            className="w-full px-3 py-2 text-sm font-theme-data bg-red-500/10 border border-red-500/40 text-red-400 hover:bg-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed rounded"
          >
            {actionInProgress === 'add' ? 'Blocking...' : 'Block Sender'}
          </button>
        </div>
      )}

      {/* Loading State */}
      {isLoading && blockedSenders.length === 0 && (
        <div className="text-center py-6 text-text-muted font-theme-data text-sm animate-pulse">
          Loading blocklist...
        </div>
      )}

      {/* Empty State */}
      {!isLoading && blockedSenders.length === 0 && (
        <div className="text-center py-6">
          <div className="text-4xl mb-2">🛡️</div>
          <p className="text-text-muted font-theme-data text-sm">No blocked senders yet.</p>
          <p className="text-text-muted/60 font-theme-data text-xs mt-1">
            Block senders to filter them from your inbox.
          </p>
        </div>
      )}

      {/* Blocked Senders List */}
      {blockedSenders.length > 0 && (
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {blockedSenders.map((blocked: BlockedSender) => (
            <div
              key={blocked.sender}
              className="flex items-center justify-between p-2 bg-bg/30 border border-slate-600/30 rounded group"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-slate-400 text-xs">⛔</span>
                  <span className="text-text font-theme-data text-sm truncate">
                    {blocked.sender}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  {blocked.reason && (
                    <span className="text-text-muted text-xs truncate max-w-[200px]">
                      {blocked.reason}
                    </span>
                  )}
                  <span className="text-text-muted/60 text-xs">
                    {formatDate(blocked.blocked_at)}
                  </span>
                </div>
              </div>
              <button
                onClick={() => handleUnblock(blocked.sender)}
                disabled={actionInProgress === blocked.sender}
                className="px-2 py-1 text-xs font-theme-data bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 disabled:opacity-50 rounded opacity-0 group-hover:opacity-100 transition-opacity"
              >
                {actionInProgress === blocked.sender ? '...' : 'Unblock'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Summary */}
      {blockedSenders.length > 0 && (
        <div className="mt-4 pt-3 border-t border-[var(--accent)]/20 text-center">
          <span className="text-text-muted text-xs font-theme-data">
            {blockedSenders.length} sender{blockedSenders.length !== 1 ? 's' : ''} blocked
          </span>
        </div>
      )}
    </div>
  );
}

export default BlocklistPanel;
