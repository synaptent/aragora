'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { GmailConnectionCard } from '@/components/inbox/GmailConnectionCard';
import { OutlookConnectionCard } from '@/components/inbox/OutlookConnectionCard';
import {
  MultiAccountSelector,
  type EmailAccount,
  type AccountType,
} from '@/components/inbox/MultiAccountSelector';
import { SyncProgressBar } from '@/components/inbox/SyncProgressBar';
import { PriorityInboxList } from '@/components/inbox/PriorityInboxList';
import { InboxQueryPanel } from '@/components/inbox/InboxQueryPanel';
import { InboxStatsCards } from '@/components/inbox/InboxStatsCards';
import { DailyDigestWidget } from '@/components/inbox/DailyDigestWidget';
import { FollowUpPanel } from '@/components/inbox/FollowUpPanel';
import { SnoozePanel } from '@/components/inbox/SnoozePanel';
import { BlocklistPanel } from '@/components/inbox/BlocklistPanel';
import { useAuth } from '@/context/AuthContext';

interface EmailStatus {
  connected: boolean;
  configured: boolean;
  email_address?: string;
  indexed_count?: number;
  last_sync?: string;
}

interface SyncStatus {
  job_status: string;
  job_progress: number;
  job_messages_synced: number;
  job_error?: string;
}

interface PrioritizationConfig {
  vip_senders: string[];
  tier_1_threshold: number;
  tier_2_threshold: number;
  enable_slack_context: boolean;
  enable_calendar_context: boolean;
}

export default function InboxPage() {
  const { config: backendConfig } = useBackend();
  const { user, tokens } = useAuth();
  const [gmailStatus, setGmailStatus] = useState<EmailStatus | null>(null);
  const [outlookStatus, setOutlookStatus] = useState<EmailStatus | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [priConfig, setPriConfig] = useState<PrioritizationConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showAccountPanel, setShowAccountPanel] = useState(false);
  const [newVip, setNewVip] = useState('');
  const [selectedAccountId, setSelectedAccountId] = useState<string | 'all'>('all');

  // Use user ID or default
  const userId = user?.id || 'default';

  // Build accounts list
  const accounts: EmailAccount[] = [];
  if (gmailStatus?.connected) {
    accounts.push({
      id: 'gmail',
      type: 'gmail',
      email: gmailStatus.email_address || 'Gmail Account',
      connected: true,
      indexed_count: gmailStatus.indexed_count || 0,
      last_sync: gmailStatus.last_sync,
    });
  }
  if (outlookStatus?.connected) {
    accounts.push({
      id: 'outlook',
      type: 'outlook',
      email: outlookStatus.email_address || 'Outlook Account',
      connected: true,
      indexed_count: outlookStatus.indexed_count || 0,
      last_sync: outlookStatus.last_sync,
    });
  }

  const hasAnyConnection = gmailStatus?.connected || outlookStatus?.connected;

  const fetchStatus = useCallback(async () => {
    try {
      // Fetch Gmail status
      const gmailResponse = await fetch(`${backendConfig.api}/api/email/config?user_id=${userId}`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (gmailResponse.ok) {
        const data = await gmailResponse.json();
        setGmailStatus({
          connected: data.gmail_connected || false,
          configured: true,
          email_address: data.email_address,
          indexed_count: data.indexed_count,
          last_sync: data.last_sync,
        });
        setPriConfig({
          vip_senders: data.vip_senders || [],
          tier_1_threshold: data.tier_1_threshold || 0.8,
          tier_2_threshold: data.tier_2_threshold || 0.5,
          enable_slack_context: data.enable_slack_context || false,
          enable_calendar_context: data.enable_calendar_context || false,
        });
      } else {
        // Fallback to legacy Gmail status endpoint
        const legacyResponse = await fetch(
          `${backendConfig.api}/api/gmail/status?user_id=${userId}`,
          { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
        );
        if (legacyResponse.ok) {
          const data = await legacyResponse.json();
          setGmailStatus(data);
        }
      }

      // Fetch Outlook status
      try {
        const outlookResponse = await fetch(
          `${backendConfig.api}/api/outlook/status?user_id=${userId}`,
          { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
        );
        if (outlookResponse.ok) {
          const data = await outlookResponse.json();
          setOutlookStatus(data);
        }
      } catch {
        // Outlook may not be configured, that's OK
      }
    } catch {
      setError('Failed to fetch email status');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, userId, tokens?.access_token]);

  const fetchSyncStatus = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/gmail/sync/status?user_id=${userId}`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setSyncStatus(data);
      }
    } catch {
      // Silently fail for sync status
    }
  }, [backendConfig.api, userId, tokens?.access_token]);

  useEffect(() => {
    fetchStatus();
    fetchSyncStatus();

    // Poll sync status when syncing
    const interval = setInterval(() => {
      if (syncStatus?.job_status === 'running') {
        fetchSyncStatus();
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchSyncStatus, syncStatus?.job_status]);

  const handleConnectGmail = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/email/gmail/oauth/url`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({
          user_id: userId,
          redirect_uri: `${window.location.origin}/inbox/callback`,
          state: userId,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        window.location.href = data.url;
      } else {
        // Fallback to legacy endpoint
        const legacyResponse = await fetch(`${backendConfig.api}/api/gmail/connect`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({
            user_id: userId,
            redirect_uri: `${window.location.origin}/inbox/callback`,
            state: userId,
          }),
        });

        if (legacyResponse.ok) {
          const data = await legacyResponse.json();
          window.location.href = data.url;
        } else if (legacyResponse.status === 401) {
          setError('Authentication required. Please login first to connect Gmail.');
        } else {
          setError('Failed to start connection. Please try again.');
        }
      }
    } catch {
      setError('Failed to connect to Gmail. Please check your connection and try again.');
    }
  }, [backendConfig.api, userId, tokens?.access_token]);

  const handleConnectOutlook = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/outlook/oauth/url`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({
          user_id: userId,
          redirect_uri: `${window.location.origin}/inbox/callback?provider=outlook`,
          state: `${userId}:outlook`,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        window.location.href = data.url;
      } else {
        setError('Failed to start Outlook connection. Please try again.');
      }
    } catch {
      setError('Failed to connect to Outlook. Please check your connection and try again.');
    }
  }, [backendConfig.api, userId, tokens?.access_token]);

  const handleAddAccount = useCallback(
    (type: AccountType) => {
      if (type === 'gmail') {
        handleConnectGmail();
      } else {
        handleConnectOutlook();
      }
    },
    [handleConnectGmail, handleConnectOutlook],
  );

  const handleDisconnectGmail = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/gmail/disconnect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({ user_id: userId }),
      });

      if (response.ok) {
        setGmailStatus({ connected: false, configured: gmailStatus?.configured || false });
        setSyncStatus(null);
      }
    } catch {
      setError('Failed to disconnect Gmail');
    }
  }, [backendConfig.api, userId, tokens?.access_token, gmailStatus?.configured]);

  const handleDisconnectOutlook = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/outlook/disconnect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({ user_id: userId }),
      });

      if (response.ok) {
        setOutlookStatus({ connected: false, configured: outlookStatus?.configured || false });
      }
    } catch {
      setError('Failed to disconnect Outlook');
    }
  }, [backendConfig.api, userId, tokens?.access_token, outlookStatus?.configured]);

  const handleSync = useCallback(
    async (fullSync: boolean = false) => {
      try {
        const response = await fetch(`${backendConfig.api}/api/gmail/sync`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({
            user_id: userId,
            full_sync: fullSync,
            max_messages: 500,
            labels: ['INBOX'],
          }),
        });

        if (response.ok) {
          fetchSyncStatus();
        }
      } catch {
        setError('Failed to start sync');
      }
    },
    [backendConfig.api, userId, tokens?.access_token, fetchSyncStatus],
  );

  const handleAddVip = useCallback(async () => {
    if (!newVip.trim()) return;
    try {
      const response = await fetch(`${backendConfig.api}/api/email/vip`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({ user_id: userId, sender_email: newVip.trim() }),
      });

      if (response.ok) {
        setPriConfig((prev) =>
          prev ? { ...prev, vip_senders: [...prev.vip_senders, newVip.trim()] } : null,
        );
        setNewVip('');
      }
    } catch {
      setError('Failed to add VIP sender');
    }
  }, [backendConfig.api, userId, tokens?.access_token, newVip]);

  const handleRemoveVip = useCallback(
    async (senderEmail: string) => {
      try {
        const response = await fetch(`${backendConfig.api}/api/email/vip`, {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({ user_id: userId, sender_email: senderEmail }),
        });

        if (response.ok) {
          setPriConfig((prev) =>
            prev
              ? { ...prev, vip_senders: prev.vip_senders.filter((s) => s !== senderEmail) }
              : null,
          );
        }
      } catch {
        setError('Failed to remove VIP sender');
      }
    },
    [backendConfig.api, userId, tokens?.access_token],
  );

  return (
    <div className="min-h-screen bg-background">
      <Scanlines />
      <CRTVignette />

      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-theme-data text-[var(--accent)]">{'>'} AI SMART INBOX</h1>
          {accounts.length > 0 && (
            <span className="text-xs text-text-muted font-theme-data">
              {accounts.length} account{accounts.length !== 1 ? 's' : ''} connected
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {hasAnyConnection && (
            <>
              <button
                onClick={() => setShowAccountPanel(!showAccountPanel)}
                className={`px-3 py-1 text-xs font-theme-data border rounded ${
                  showAccountPanel
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'bg-transparent border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10'
                }`}
              >
                Accounts
              </button>
              <button
                onClick={() => setShowConfig(!showConfig)}
                className={`px-3 py-1 text-xs font-theme-data border rounded ${
                  showConfig
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'bg-transparent border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10'
                }`}
              >
                Config
              </button>
            </>
          )}
        </div>
      </div>

      <main>
        {error && (
          <div className="mb-4 p-3 bg-acid-red/10 border border-acid-red/30 rounded font-theme-data text-sm">
            <div className="flex items-center justify-between">
              <span className="text-acid-red">{error}</span>
              <button
                onClick={() => setError(null)}
                className="text-acid-red/70 hover:text-acid-red"
              >
                [X]
              </button>
            </div>
            {error.toLowerCase().includes('authentication') && !user && (
              <div className="mt-2 pt-2 border-t border-acid-red/20">
                <Link
                  href="/auth/login"
                  className="inline-flex items-center gap-2 text-accent hover:text-accent/80"
                >
                  <span>-&gt;</span>
                  <span>Login to continue</span>
                </Link>
              </div>
            )}
          </div>
        )}

        {/* Account Management Panel */}
        {showAccountPanel && (
          <div className="mb-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-1">
              <MultiAccountSelector
                accounts={accounts}
                selectedAccountId={selectedAccountId}
                onSelectAccount={setSelectedAccountId}
                onAddAccount={handleAddAccount}
              />
            </div>
            <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-4">
              <PanelErrorBoundary panelName="Gmail Connection">
                <GmailConnectionCard
                  status={gmailStatus}
                  loading={loading}
                  onConnect={handleConnectGmail}
                  onDisconnect={handleDisconnectGmail}
                />
              </PanelErrorBoundary>
              <PanelErrorBoundary panelName="Outlook Connection">
                <OutlookConnectionCard
                  status={outlookStatus}
                  loading={loading}
                  onConnect={handleConnectOutlook}
                  onDisconnect={handleDisconnectOutlook}
                />
              </PanelErrorBoundary>
            </div>
          </div>
        )}

        {/* Connection Status (simple view when account panel is hidden) */}
        {!showAccountPanel && hasAnyConnection && (
          <div className="mb-4 flex items-center gap-4">
            {gmailStatus?.connected && (
              <div className="flex items-center gap-2 px-3 py-1 bg-[var(--surface)] border border-[var(--border)] rounded text-xs">
                <span className="w-2 h-2 bg-green-400 rounded-full" />
                <span className="font-theme-data">{gmailStatus.email_address}</span>
              </div>
            )}
            {outlookStatus?.connected && (
              <div className="flex items-center gap-2 px-3 py-1 bg-[var(--surface)] border border-[var(--border)] rounded text-xs">
                <span className="w-2 h-2 bg-[#0078D4] rounded-full" />
                <span className="font-theme-data">{outlookStatus.email_address}</span>
              </div>
            )}
          </div>
        )}

        {/* Prioritization Config Panel */}
        {showConfig && priConfig && (
          <div className="mb-6 border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
            <h3 className="text-[var(--accent)] font-theme-data text-sm mb-4">
              Prioritization Settings
            </h3>

            {/* VIP Senders */}
            <div className="mb-4">
              <label className="text-text-muted text-xs font-theme-data block mb-2">
                VIP Senders (always prioritized)
              </label>
              <div className="flex gap-2 mb-2">
                <input
                  type="email"
                  value={newVip}
                  onChange={(e) => setNewVip(e.target.value)}
                  placeholder="email@example.com"
                  className="flex-1 px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm rounded focus:outline-none focus:border-[var(--accent)]"
                />
                <button
                  onClick={handleAddVip}
                  className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded"
                >
                  Add
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {priConfig.vip_senders.map((sender) => (
                  <span
                    key={sender}
                    className="px-2 py-1 text-xs bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded text-[var(--accent)] flex items-center gap-2"
                  >
                    {sender}
                    <button onClick={() => handleRemoveVip(sender)} className="hover:text-acid-red">
                      x
                    </button>
                  </span>
                ))}
                {priConfig.vip_senders.length === 0 && (
                  <span className="text-text-muted text-xs">No VIP senders configured</span>
                )}
              </div>
            </div>

            {/* Context Integration Status */}
            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 border border-[var(--accent)]/20 rounded">
                <span className="text-text-muted text-xs font-theme-data">Slack Context</span>
                <div
                  className={`text-sm font-theme-data mt-1 ${priConfig.enable_slack_context ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                >
                  {priConfig.enable_slack_context ? 'Enabled' : 'Disabled'}
                </div>
              </div>
              <div className="p-3 border border-[var(--accent)]/20 rounded">
                <span className="text-text-muted text-xs font-theme-data">Calendar Context</span>
                <div
                  className={`text-sm font-theme-data mt-1 ${priConfig.enable_calendar_context ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                >
                  {priConfig.enable_calendar_context ? 'Enabled' : 'Disabled'}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Blocklist Panel - only show when config is visible */}
        {showConfig && hasAnyConnection && (
          <div className="mb-6">
            <PanelErrorBoundary panelName="Blocklist">
              <BlocklistPanel
                apiBase={backendConfig.api}
                userId={userId}
                authToken={tokens?.access_token}
              />
            </PanelErrorBoundary>
          </div>
        )}

        {/* Sync Progress */}
        {hasAnyConnection && syncStatus && (
          <PanelErrorBoundary panelName="Sync Progress">
            <SyncProgressBar
              syncStatus={syncStatus}
              indexedCount={(gmailStatus?.indexed_count || 0) + (outlookStatus?.indexed_count || 0)}
              lastSync={gmailStatus?.last_sync || outlookStatus?.last_sync}
              onSync={() => handleSync(false)}
              onFullSync={() => handleSync(true)}
            />
          </PanelErrorBoundary>
        )}

        {/* Main Content */}
        {hasAnyConnection && (
          <>
            {/* Stats Overview */}
            <div className="mt-6">
              <PanelErrorBoundary panelName="Inbox Stats">
                <InboxStatsCards
                  apiBase={backendConfig.api}
                  userId={userId}
                  authToken={tokens?.access_token}
                />
              </PanelErrorBoundary>
            </div>

            {/* Main Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
              {/* Priority Inbox List */}
              <div className="lg:col-span-2">
                <PanelErrorBoundary panelName="Priority Inbox">
                  <PriorityInboxList
                    apiBase={backendConfig.api}
                    userId={userId}
                    authToken={tokens?.access_token}
                  />
                </PanelErrorBoundary>
              </div>

              {/* Right Sidebar */}
              <div className="lg:col-span-1 space-y-6">
                {/* Daily Digest */}
                <PanelErrorBoundary panelName="Daily Digest">
                  <DailyDigestWidget
                    apiBase={backendConfig.api}
                    userId={userId}
                    authToken={tokens?.access_token}
                  />
                </PanelErrorBoundary>

                {/* Q&A Panel */}
                <PanelErrorBoundary panelName="Inbox Q&A">
                  <InboxQueryPanel
                    apiBase={backendConfig.api}
                    userId={userId}
                    authToken={tokens?.access_token}
                  />
                </PanelErrorBoundary>

                {/* Follow-Up Tracking */}
                <PanelErrorBoundary panelName="Follow-Up Tracking">
                  <FollowUpPanel
                    apiBase={backendConfig.api}
                    userId={userId}
                    authToken={tokens?.access_token}
                  />
                </PanelErrorBoundary>

                {/* Snooze Management */}
                <PanelErrorBoundary panelName="Snooze Management">
                  <SnoozePanel
                    apiBase={backendConfig.api}
                    userId={userId}
                    authToken={tokens?.access_token}
                  />
                </PanelErrorBoundary>
              </div>
            </div>
          </>
        )}

        {/* Not Connected State */}
        {!loading && !hasAnyConnection && (
          <div className="mt-8 text-center">
            <div className="text-6xl mb-4">📬</div>
            <h2 className="text-xl font-theme-data text-accent mb-2">Connect Your Email</h2>
            <p className="text-muted font-theme-data text-sm mb-6 max-w-md mx-auto">
              Connect your Gmail or Outlook account to get AI-powered email prioritization with our
              3-tier scoring system. Critical emails float to the top, newsletters and bulk mail
              sink to the bottom.
            </p>
            <div className="flex flex-wrap justify-center gap-4 mb-6 text-xs font-theme-data">
              <div className="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-red-400">
                Critical - Needs immediate attention
              </div>
              <div className="px-3 py-2 bg-orange-500/10 border border-orange-500/30 rounded text-orange-400">
                High - Important, respond today
              </div>
              <div className="px-3 py-2 bg-yellow-500/10 border border-yellow-500/30 rounded text-yellow-400">
                Medium - Standard priority
              </div>
              <div className="px-3 py-2 bg-blue-500/10 border border-blue-500/30 rounded text-blue-400">
                Low - Can wait
              </div>
              <div className="px-3 py-2 bg-gray-500/10 border border-gray-500/30 rounded text-gray-400">
                Defer - Newsletters, bulk mail
              </div>
            </div>

            {/* Authentication required message */}
            {!user && (
              <div className="mb-6 p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg max-w-md mx-auto">
                <p className="text-amber-400 font-theme-data text-sm mb-3">
                  Login required to connect email
                </p>
                <p className="text-muted text-xs mb-4">
                  You need to be logged in to connect your email accounts. This ensures your emails
                  are securely linked to your account.
                </p>
                <Link
                  href="/auth/login"
                  className="inline-flex items-center gap-2 px-6 py-2.5 bg-accent/20 hover:bg-accent/30 border border-accent/40 rounded-md text-accent font-theme-data text-sm transition-colors"
                >
                  <span>-&gt;</span>
                  <span>Login</span>
                </Link>
              </div>
            )}

            {/* Connect buttons (only when authenticated) */}
            {user && (
              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <button
                  onClick={handleConnectGmail}
                  className="inline-flex items-center justify-center gap-3 px-6 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg hover:border-[#EA4335]/50 transition-colors"
                >
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="#EA4335">
                    <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z" />
                  </svg>
                  <span className="font-theme-data text-sm">Connect Gmail</span>
                </button>
                <button
                  onClick={handleConnectOutlook}
                  className="inline-flex items-center justify-center gap-3 px-6 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg hover:border-[#0078D4]/50 transition-colors"
                >
                  <svg className="w-5 h-5 text-[#0078D4]" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M7.88 12.04q0 .45-.11.87-.1.41-.33.74-.22.33-.58.52-.37.2-.87.2t-.85-.2q-.35-.21-.57-.55-.22-.33-.33-.75-.1-.42-.1-.86t.1-.87q.1-.43.34-.76.22-.34.59-.54.36-.2.87-.2t.86.2q.35.21.57.55.22.34.31.77.1.43.1.88zM24 12v9.38q0 .46-.33.8-.33.32-.8.32H7.13q-.46 0-.8-.33-.32-.33-.32-.8V18H1q-.41 0-.7-.3-.3-.29-.3-.7V7q0-.41.3-.7Q.58 6 1 6h6.13V2.55q0-.44.3-.75.3-.3.7-.3h12.74q.41 0 .7.3.3.3.3.75V11q0 .41-.3.7-.29.3-.7.3H19.8v.8h3.4q.4 0 .7.3.3.3.3.7v.2h-5.6v-.1l-.2-.4V12zm-17.54-.5q0-.93-.26-1.64-.26-.72-.75-1.22-.48-.5-1.18-.76-.69-.27-1.57-.27-.9 0-1.61.26-.7.27-1.2.77-.5.51-.76 1.22-.27.71-.27 1.64 0 .92.27 1.63.26.72.76 1.23.5.51 1.2.78.72.27 1.61.27.88 0 1.57-.27.69-.27 1.18-.78.49-.51.75-1.23.26-.71.26-1.63zm17.14 5.5v-4H7.8v4h15.8z" />
                  </svg>
                  <span className="font-theme-data text-sm">Connect Outlook</span>
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
