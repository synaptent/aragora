'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';
import { PriorityInboxList, type PrioritizedEmail } from './PriorityInboxList';
import { TriageRulesPanel } from './TriageRulesPanel';
import { QuickActionsBar } from './QuickActionsBar';
import { SenderInsightsPanel } from './SenderInsightsPanel';
import { DailyDigestWidget } from './DailyDigestWidget';

type CommandCenterTab = 'inbox' | 'rules' | 'insights';

interface InboxStats {
  total: number;
  critical: number;
  actionRequired: number;
  deferred: number;
  processed: number;
}

interface SenderProfile {
  email: string;
  name: string;
  isVip: boolean;
  isInternal: boolean;
  responseRate: number;
  avgResponseTime: string;
  totalEmails: number;
  lastContact: string;
}

export function CommandCenter() {
  const apiBase = API_BASE_URL;
  const [activeTab, setActiveTab] = useState<CommandCenterTab>('inbox');
  const [emails, setEmails] = useState<PrioritizedEmail[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<PrioritizedEmail | null>(null);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<InboxStats>({
    total: 0,
    critical: 0,
    actionRequired: 0,
    deferred: 0,
    processed: 0,
  });
  const [senderProfile, setSenderProfile] = useState<SenderProfile | null>(null);
  const [showInsights, setShowInsights] = useState(false);

  // Fetch emails
  const fetchEmails = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/api/email/inbox?prioritized=true&limit=50`);
      if (response.ok) {
        const data = await response.json();
        setEmails(data.emails || []);
        setStats({
          total: data.total || 0,
          critical:
            data.emails?.filter((e: PrioritizedEmail) => e.priority === 'critical').length || 0,
          actionRequired:
            data.emails?.filter((e: PrioritizedEmail) => e.priority === 'high').length || 0,
          deferred: data.emails?.filter((e: PrioritizedEmail) => e.priority === 'low').length || 0,
          processed: data.processed || 0,
        });
      }
    } catch (error) {
      logger.error('Failed to fetch emails:', error);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchEmails();
    // Refresh every 30 seconds
    const interval = setInterval(fetchEmails, 30000);
    return () => clearInterval(interval);
  }, [fetchEmails]);

  // Handle email selection
  const handleSelectEmail = useCallback(
    async (email: PrioritizedEmail) => {
      setSelectedEmail(email);
      setShowInsights(true);

      // Fetch sender profile
      try {
        const response = await fetch(
          `${apiBase}/api/email/sender-profile?email=${encodeURIComponent(email.from_address)}`,
        );
        if (response.ok) {
          const profile = await response.json();
          setSenderProfile(profile);
        }
      } catch (error) {
        logger.error('Failed to fetch sender profile:', error);
        setSenderProfile(null);
      }
    },
    [apiBase],
  );

  // Quick actions
  const handleQuickAction = useCallback(
    async (action: string, emailIds?: string[]) => {
      const ids = emailIds || (selectedEmail ? [selectedEmail.id] : []);
      if (ids.length === 0) return;

      try {
        const response = await fetch(`${apiBase}/api/email/actions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, emailIds: ids }),
        });

        if (response.ok) {
          // Refresh inbox after action
          await fetchEmails();
          if (action === 'archive' || action === 'delete') {
            setSelectedEmail(null);
            setShowInsights(false);
          }
        }
      } catch (error) {
        logger.error('Failed to execute action:', error);
      }
    },
    [selectedEmail, fetchEmails, apiBase],
  );

  // Bulk actions
  const handleBulkAction = useCallback(
    async (action: string, filter: string) => {
      let emailIds: string[] = [];

      switch (filter) {
        case 'low':
          emailIds = emails.filter((e) => e.priority === 'low').map((e) => e.id);
          break;
        case 'deferred':
          emailIds = emails.filter((e) => e.priority === 'defer').map((e) => e.id);
          break;
        case 'spam':
          emailIds = emails.filter((e) => e.priority === 'spam').map((e) => e.id);
          break;
        case 'read':
          emailIds = emails.filter((e) => e.read).map((e) => e.id);
          break;
        default:
          return;
      }

      if (emailIds.length > 0) {
        await handleQuickAction(action, emailIds);
      }
    },
    [emails, handleQuickAction],
  );

  const tabs = [
    { id: 'inbox', label: 'Inbox', badge: stats.total },
    { id: 'rules', label: 'Rules' },
    { id: 'insights', label: 'Insights' },
  ];

  return (
    <div className="space-y-4">
      {/* Stats Summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Total" value={stats.total} color="text-[var(--text)]" />
        <StatCard
          label="Critical"
          value={stats.critical}
          color="text-red-400"
          pulse={stats.critical > 0}
        />
        <StatCard label="Action Required" value={stats.actionRequired} color="text-yellow-400" />
        <StatCard label="Deferred" value={stats.deferred} color="text-[var(--text-muted)]" />
        <StatCard label="Processed Today" value={stats.processed} color="text-green-400" />
      </div>

      {/* Quick Actions Bar */}
      <QuickActionsBar
        selectedEmail={selectedEmail}
        onAction={handleQuickAction}
        onBulkAction={handleBulkAction}
        emailCount={emails.length}
        lowPriorityCount={emails.filter((e) => e.priority === 'low').length}
      />

      {/* Tab Navigation */}
      <div className="flex items-center gap-2 border-b border-[var(--border)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as CommandCenterTab)}
            className={`px-4 py-2 text-sm font-theme-data transition-colors relative ${
              activeTab === tab.id
                ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            {tab.label}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span className="ml-2 px-1.5 py-0.5 text-xs bg-[var(--acid-green)]/20 text-[var(--acid-green)] rounded">
                {tab.badge}
              </span>
            )}
          </button>
        ))}

        {/* Daily Digest Toggle */}
        <div className="ml-auto">
          <DailyDigestWidget compact />
        </div>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: Main Content Area */}
        <div className="lg:col-span-2">
          {activeTab === 'inbox' && (
            <PriorityInboxList
              emails={emails}
              loading={loading}
              selectedId={selectedEmail?.id}
              onSelect={handleSelectEmail}
              onRefresh={fetchEmails}
            />
          )}

          {activeTab === 'rules' && <TriageRulesPanel onRuleChange={fetchEmails} />}

          {activeTab === 'insights' && (
            <div className="bg-[var(--surface)] border border-[var(--border)] p-6 rounded">
              <h3 className="text-lg font-theme-data text-[var(--acid-green)] mb-4">
                {'>'} INBOX INSIGHTS
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <InsightCard
                  title="Top Senders"
                  description="Most frequent email sources"
                  icon="📨"
                />
                <InsightCard
                  title="Response Patterns"
                  description="Your email response habits"
                  icon="⏱️"
                />
                <InsightCard
                  title="Priority Accuracy"
                  description="How well AI predicted importance"
                  icon="🎯"
                />
                <InsightCard title="Time Saved" description="Hours saved by AI triage" icon="💎" />
              </div>
            </div>
          )}
        </div>

        {/* Right: Sender Insights Panel */}
        <div className="lg:col-span-1">
          {showInsights && selectedEmail ? (
            <SenderInsightsPanel
              email={selectedEmail}
              profile={senderProfile}
              onClose={() => {
                setShowInsights(false);
                setSelectedEmail(null);
              }}
              onAction={handleQuickAction}
            />
          ) : (
            <div className="bg-[var(--surface)] border border-[var(--border)] p-6 rounded text-center">
              <div className="text-4xl mb-4">📧</div>
              <p className="text-[var(--text-muted)] font-theme-data text-sm">
                Select an email to view sender insights
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Keyboard Shortcuts Help */}
      <div className="text-xs font-theme-data text-[var(--text-muted)] flex items-center gap-4 mt-4">
        <span>Shortcuts:</span>
        <span>
          <kbd className="px-1 bg-[var(--surface)] rounded">j/k</kbd> Navigate
        </span>
        <span>
          <kbd className="px-1 bg-[var(--surface)] rounded">e</kbd> Archive
        </span>
        <span>
          <kbd className="px-1 bg-[var(--surface)] rounded">s</kbd> Snooze
        </span>
        <span>
          <kbd className="px-1 bg-[var(--surface)] rounded">r</kbd> Reply
        </span>
        <span>
          <kbd className="px-1 bg-[var(--surface)] rounded">?</kbd> Help
        </span>
      </div>
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: number;
  color: string;
  pulse?: boolean;
}

function StatCard({ label, value, color, pulse }: StatCardProps) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-3 rounded">
      <div
        className={`text-2xl font-theme-data font-bold ${color} ${pulse ? 'animate-pulse' : ''}`}
      >
        {value}
      </div>
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

interface InsightCardProps {
  title: string;
  description: string;
  icon: string;
}

function InsightCard({ title, description, icon }: InsightCardProps) {
  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] p-4 rounded hover:border-[var(--acid-green)]/30 transition-colors cursor-pointer">
      <div className="text-2xl mb-2">{icon}</div>
      <div className="font-theme-data text-sm text-[var(--text)]">{title}</div>
      <div className="text-xs text-[var(--text-muted)]">{description}</div>
    </div>
  );
}

export default CommandCenter;
