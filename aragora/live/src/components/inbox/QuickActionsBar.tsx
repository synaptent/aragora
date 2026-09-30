'use client';

import { useState } from 'react';
import type { PrioritizedEmail } from './PriorityInboxList';

interface QuickActionsBarProps {
  selectedEmail: PrioritizedEmail | null;
  onAction: (action: string, emailIds?: string[]) => Promise<void>;
  onBulkAction: (action: string, filter: string) => Promise<void>;
  emailCount: number;
  lowPriorityCount: number;
}

export function QuickActionsBar({
  selectedEmail,
  onAction,
  onBulkAction,
  emailCount,
  lowPriorityCount,
}: QuickActionsBarProps) {
  const [loading, setLoading] = useState<string | null>(null);
  const [showBulkMenu, setShowBulkMenu] = useState(false);

  const handleAction = async (action: string) => {
    setLoading(action);
    try {
      await onAction(action);
    } finally {
      setLoading(null);
    }
  };

  const handleBulkAction = async (action: string, filter: string) => {
    setLoading(`bulk-${action}-${filter}`);
    setShowBulkMenu(false);
    try {
      await onBulkAction(action, filter);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-3 rounded">
      <div className="flex items-center justify-between flex-wrap gap-3">
        {/* Single Email Actions */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-[var(--text-muted)] mr-2">
            {selectedEmail ? 'Selected:' : 'Quick Actions:'}
          </span>

          <ActionButton
            icon="📥"
            label="Archive"
            onClick={() => handleAction('archive')}
            loading={loading === 'archive'}
            disabled={!selectedEmail}
          />

          <ActionButton
            icon="⏰"
            label="Snooze"
            onClick={() => handleAction('snooze')}
            loading={loading === 'snooze'}
            disabled={!selectedEmail}
          />

          <ActionButton
            icon="✨"
            label="Mark Important"
            onClick={() => handleAction('mark_important')}
            loading={loading === 'mark_important'}
            disabled={!selectedEmail}
          />

          <ActionButton
            icon="↩️"
            label="Reply"
            onClick={() => handleAction('reply')}
            loading={loading === 'reply'}
            disabled={!selectedEmail}
          />

          <ActionButton
            icon="➡️"
            label="Forward"
            onClick={() => handleAction('forward')}
            loading={loading === 'forward'}
            disabled={!selectedEmail}
          />

          <div className="w-px h-6 bg-[var(--border)] mx-2" />

          <ActionButton
            icon="🚫"
            label="Spam"
            onClick={() => handleAction('spam')}
            loading={loading === 'spam'}
            disabled={!selectedEmail}
            variant="danger"
          />
        </div>

        {/* Bulk Actions */}
        <div className="relative">
          <button
            onClick={() => setShowBulkMenu(!showBulkMenu)}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            <span>⚡</span>
            <span>Bulk Actions</span>
            <span className="text-[var(--text-muted)]">({emailCount})</span>
          </button>

          {showBulkMenu && (
            <div className="absolute right-0 top-full mt-1 w-64 bg-[var(--surface)] border border-[var(--border)] rounded shadow-lg z-10">
              <div className="p-2 border-b border-[var(--border)]">
                <span className="text-xs font-theme-data text-[var(--text-muted)]">
                  Bulk Operations
                </span>
              </div>

              <div className="p-1">
                <BulkActionItem
                  label="Archive all low priority"
                  count={lowPriorityCount}
                  onClick={() => handleBulkAction('archive', 'low')}
                  loading={loading === 'bulk-archive-low'}
                />

                <BulkActionItem
                  label="Archive all deferred"
                  onClick={() => handleBulkAction('archive', 'deferred')}
                  loading={loading === 'bulk-archive-deferred'}
                />

                <BulkActionItem
                  label="Delete all spam"
                  onClick={() => handleBulkAction('delete', 'spam')}
                  loading={loading === 'bulk-delete-spam'}
                  variant="danger"
                />

                <BulkActionItem
                  label="Mark all read as done"
                  onClick={() => handleBulkAction('archive', 'read')}
                  loading={loading === 'bulk-archive-read'}
                />

                <div className="border-t border-[var(--border)] my-1" />

                <BulkActionItem
                  label="Snooze all non-urgent (1 day)"
                  onClick={() => handleBulkAction('snooze_1d', 'low')}
                  loading={loading === 'bulk-snooze_1d-low'}
                />

                <BulkActionItem
                  label="Run AI re-prioritization"
                  onClick={() => handleBulkAction('reprioritize', 'all')}
                  loading={loading === 'bulk-reprioritize-all'}
                  variant="primary"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Processing indicator */}
      {loading && (
        <div className="mt-2 flex items-center gap-2 text-xs font-theme-data text-[var(--acid-cyan)]">
          <span className="w-2 h-2 bg-[var(--acid-cyan)] rounded-full animate-pulse" />
          <span>Processing...</span>
        </div>
      )}
    </div>
  );
}

interface ActionButtonProps {
  icon: string;
  label: string;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  variant?: 'default' | 'danger' | 'primary';
}

function ActionButton({
  icon,
  label,
  onClick,
  loading,
  disabled,
  variant = 'default',
}: ActionButtonProps) {
  const variantClasses = {
    default: 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg)]',
    danger: 'text-red-400/70 hover:text-red-400 hover:bg-red-400/10',
    primary: 'text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10',
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      title={label}
      className={`p-2 rounded transition-colors ${variantClasses[variant]} ${
        disabled ? 'opacity-50 cursor-not-allowed' : ''
      } ${loading ? 'animate-pulse' : ''}`}
    >
      <span className="text-lg">{loading ? '⏳' : icon}</span>
    </button>
  );
}

interface BulkActionItemProps {
  label: string;
  count?: number;
  onClick: () => void;
  loading?: boolean;
  variant?: 'default' | 'danger' | 'primary';
}

function BulkActionItem({
  label,
  count,
  onClick,
  loading,
  variant = 'default',
}: BulkActionItemProps) {
  const variantClasses = {
    default: 'hover:bg-[var(--bg)]',
    danger: 'hover:bg-red-400/10 text-red-400',
    primary: 'hover:bg-[var(--acid-green)]/10 text-[var(--acid-green)]',
  };

  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`w-full px-3 py-2 text-left text-xs font-theme-data rounded transition-colors ${
        variantClasses[variant]
      } ${loading ? 'opacity-50' : ''}`}
    >
      <span className="flex items-center justify-between">
        <span>
          {loading ? '⏳ ' : ''}
          {label}
        </span>
        {count !== undefined && count > 0 && (
          <span className="text-[var(--text-muted)]">({count})</span>
        )}
      </span>
    </button>
  );
}

export default QuickActionsBar;
