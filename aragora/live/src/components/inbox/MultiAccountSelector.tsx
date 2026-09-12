'use client';

import { useState } from 'react';

export type AccountType = 'gmail' | 'outlook';

export interface EmailAccount {
  id: string;
  type: AccountType;
  email: string;
  connected: boolean;
  indexed_count: number;
  last_sync?: string;
}

interface MultiAccountSelectorProps {
  accounts: EmailAccount[];
  selectedAccountId: string | 'all';
  onSelectAccount: (accountId: string | 'all') => void;
  onAddAccount: (type: AccountType) => void;
}

export function MultiAccountSelector({
  accounts,
  selectedAccountId,
  onSelectAccount,
  onAddAccount,
}: MultiAccountSelectorProps) {
  const [showAddMenu, setShowAddMenu] = useState(false);

  const connectedAccounts = accounts.filter((a) => a.connected);
  const totalMessages = connectedAccounts.reduce((sum, a) => sum + a.indexed_count, 0);

  const getAccountIcon = (type: AccountType) => {
    if (type === 'gmail') {
      return (
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
          <path
            d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z"
            fill="#EA4335"
          />
        </svg>
      );
    }
    return (
      <svg className="w-4 h-4 text-[#0078D4]" viewBox="0 0 24 24" fill="currentColor">
        <path d="M7.88 12.04q0 .45-.11.87-.1.41-.33.74-.22.33-.58.52-.37.2-.87.2t-.85-.2q-.35-.21-.57-.55-.22-.33-.33-.75-.1-.42-.1-.86t.1-.87q.1-.43.34-.76.22-.34.59-.54.36-.2.87-.2t.86.2q.35.21.57.55.22.34.31.77.1.43.1.88zM24 12v9.38q0 .46-.33.8-.33.32-.8.32H7.13q-.46 0-.8-.33-.32-.33-.32-.8V18H1q-.41 0-.7-.3-.3-.29-.3-.7V7q0-.41.3-.7Q.58 6 1 6h6.13V2.55q0-.44.3-.75.3-.3.7-.3h12.74q.41 0 .7.3.3.3.3.75V11q0 .41-.3.7-.29.3-.7.3H19.8v.8h3.4q.4 0 .7.3.3.3.3.7v.2h-5.6v-.1l-.2-.4V12zm-17.54-.5q0-.93-.26-1.64-.26-.72-.75-1.22-.48-.5-1.18-.76-.69-.27-1.57-.27-.9 0-1.61.26-.7.27-1.2.77-.5.51-.76 1.22-.27.71-.27 1.64 0 .92.27 1.63.26.72.76 1.23.5.51 1.2.78.72.27 1.61.27.88 0 1.57-.27.69-.27 1.18-.78.49-.51.75-1.23.26-.71.26-1.63zm17.14 5.5v-4H7.8v4h15.8z" />
      </svg>
    );
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-theme-data text-[var(--text-muted)]">Email Accounts</h3>
        <div className="relative">
          <button
            onClick={() => setShowAddMenu(!showAddMenu)}
            className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            + Add
          </button>
          {showAddMenu && (
            <div className="absolute right-0 top-full mt-1 bg-[var(--surface)] border border-[var(--border)] rounded shadow-lg z-10 min-w-[150px]">
              <button
                onClick={() => {
                  onAddAccount('gmail');
                  setShowAddMenu(false);
                }}
                className="w-full px-3 py-2 text-xs font-theme-data text-left hover:bg-[var(--bg)] flex items-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="#EA4335">
                  <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z" />
                </svg>
                Gmail
              </button>
              <button
                onClick={() => {
                  onAddAccount('outlook');
                  setShowAddMenu(false);
                }}
                className="w-full px-3 py-2 text-xs font-theme-data text-left hover:bg-[var(--bg)] flex items-center gap-2"
              >
                <svg className="w-4 h-4 text-[#0078D4]" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M7.88 12.04q0 .45-.11.87-.1.41-.33.74-.22.33-.58.52-.37.2-.87.2t-.85-.2q-.35-.21-.57-.55-.22-.33-.33-.75-.1-.42-.1-.86t.1-.87q.1-.43.34-.76.22-.34.59-.54.36-.2.87-.2t.86.2q.35.21.57.55.22.34.31.77.1.43.1.88zM24 12v9.38q0 .46-.33.8-.33.32-.8.32H7.13q-.46 0-.8-.33-.32-.33-.32-.8V18H1q-.41 0-.7-.3-.3-.29-.3-.7V7q0-.41.3-.7Q.58 6 1 6h6.13V2.55q0-.44.3-.75.3-.3.7-.3h12.74q.41 0 .7.3.3.3.3.75V11q0 .41-.3.7-.29.3-.7.3H19.8v.8h3.4q.4 0 .7.3.3.3.3.7v.2h-5.6v-.1l-.2-.4V12zm-17.54-.5q0-.93-.26-1.64-.26-.72-.75-1.22-.48-.5-1.18-.76-.69-.27-1.57-.27-.9 0-1.61.26-.7.27-1.2.77-.5.51-.76 1.22-.27.71-.27 1.64 0 .92.27 1.63.26.72.76 1.23.5.51 1.2.78.72.27 1.61.27.88 0 1.57-.27.69-.27 1.18-.78.49-.51.75-1.23.26-.71.26-1.63zm17.14 5.5v-4H7.8v4h15.8z" />
                </svg>
                Outlook
              </button>
            </div>
          )}
        </div>
      </div>

      {/* All Accounts Option */}
      {connectedAccounts.length > 1 && (
        <button
          onClick={() => onSelectAccount('all')}
          className={`w-full p-2 mb-2 rounded flex items-center justify-between transition-colors ${
            selectedAccountId === 'all'
              ? 'bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/40'
              : 'bg-[var(--bg)] border border-transparent hover:border-[var(--border)]'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="text-lg">📬</span>
            <div className="text-left">
              <div className="text-sm font-theme-data">All Accounts</div>
              <div className="text-xs text-[var(--text-muted)]">
                {connectedAccounts.length} accounts • {totalMessages.toLocaleString()} messages
              </div>
            </div>
          </div>
          {selectedAccountId === 'all' && (
            <span className="w-2 h-2 bg-[var(--acid-green)] rounded-full" />
          )}
        </button>
      )}

      {/* Individual Accounts */}
      <div className="space-y-1">
        {connectedAccounts.map((account) => (
          <button
            key={account.id}
            onClick={() => onSelectAccount(account.id)}
            className={`w-full p-2 rounded flex items-center justify-between transition-colors ${
              selectedAccountId === account.id
                ? 'bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/40'
                : 'bg-[var(--bg)] border border-transparent hover:border-[var(--border)]'
            }`}
          >
            <div className="flex items-center gap-2">
              {getAccountIcon(account.type)}
              <div className="text-left">
                <div className="text-sm font-theme-data truncate max-w-[180px]">
                  {account.email}
                </div>
                <div className="text-xs text-[var(--text-muted)]">
                  {account.indexed_count.toLocaleString()} messages
                </div>
              </div>
            </div>
            {selectedAccountId === account.id && (
              <span className="w-2 h-2 bg-[var(--acid-green)] rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* No Accounts Connected */}
      {connectedAccounts.length === 0 && (
        <div className="text-center py-4">
          <p className="text-xs text-[var(--text-muted)] mb-2">No email accounts connected</p>
          <p className="text-xs text-[var(--text-muted)]">
            Connect Gmail or Outlook to get started
          </p>
        </div>
      )}

      {/* Sync Status */}
      {connectedAccounts.length > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--border)]">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-muted)]">Total indexed</span>
            <span className="font-theme-data text-[var(--acid-green)]">
              {totalMessages.toLocaleString()} messages
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
