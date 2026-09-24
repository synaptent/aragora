'use client';

import type { PrioritizedEmail } from './PriorityInboxList';

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

interface SenderInsightsPanelProps {
  email: PrioritizedEmail;
  profile: SenderProfile | null;
  onClose: () => void;
  onAction: (action: string) => Promise<void>;
}

export function SenderInsightsPanel({
  email,
  profile,
  onClose,
  onAction,
}: SenderInsightsPanelProps) {
  const priorityColors: Record<string, string> = {
    critical: 'bg-red-500',
    high: 'bg-yellow-500',
    normal: 'bg-blue-500',
    low: 'bg-gray-500',
    defer: 'bg-gray-400',
    spam: 'bg-red-800',
    blocked: 'bg-slate-600',
  };

  const priorityLabels: Record<string, string> = {
    critical: 'CRITICAL',
    high: 'HIGH',
    normal: 'NORMAL',
    low: 'LOW',
    defer: 'DEFER',
    spam: 'SPAM',
    blocked: 'BLOCKED',
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-[var(--border)] flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2 h-2 rounded-full ${priorityColors[email.priority]}`} />
            <span className="text-xs font-theme-data text-[var(--text-muted)]">
              {priorityLabels[email.priority]}
            </span>
            {profile?.isVip && (
              <span className="px-1.5 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 rounded">
                VIP
              </span>
            )}
            {profile?.isInternal && (
              <span className="px-1.5 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded">
                Internal
              </span>
            )}
          </div>
          <h3 className="font-theme-data text-sm text-[var(--text)] truncate">
            {email.from_address}
          </h3>
          <p className="text-xs text-[var(--text-muted)] truncate">{email.subject}</p>
        </div>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text)] p-1">
          ✕
        </button>
      </div>

      {/* Sender Stats */}
      {profile && (
        <div className="p-4 border-b border-[var(--border)]">
          <h4 className="text-xs font-theme-data text-[var(--acid-green)] mb-3">
            {'>'} SENDER PROFILE
          </h4>
          <div className="grid grid-cols-2 gap-3">
            <StatItem label="Total Emails" value={profile.totalEmails.toString()} />
            <StatItem label="Response Rate" value={`${Math.round(profile.responseRate * 100)}%`} />
            <StatItem label="Avg Response" value={profile.avgResponseTime} />
            <StatItem label="Last Contact" value={profile.lastContact} />
          </div>
        </div>
      )}

      {/* AI Analysis */}
      <div className="p-4 border-b border-[var(--border)]">
        <h4 className="text-xs font-theme-data text-[var(--acid-green)] mb-3">{'>'} AI ANALYSIS</h4>
        <div className="space-y-2">
          <AnalysisItem
            label="Urgency"
            value={
              email.priority === 'critical' ? 'High' : email.priority === 'high' ? 'Medium' : 'Low'
            }
            color={
              email.priority === 'critical' ? 'red' : email.priority === 'high' ? 'yellow' : 'green'
            }
          />
          <AnalysisItem
            label="Confidence"
            value={`${Math.round((email.confidence || 0.8) * 100)}%`}
            color="cyan"
          />
          <AnalysisItem label="Category" value={email.category || 'General'} color="default" />
        </div>

        {email.reasoning && (
          <div className="mt-3 p-2 bg-[var(--bg)] rounded text-xs font-theme-data text-[var(--text-muted)]">
            <span className="text-[var(--acid-cyan)]">Reasoning:</span> {email.reasoning}
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="p-4">
        <h4 className="text-xs font-theme-data text-[var(--acid-green)] mb-3">
          {'>'} QUICK ACTIONS
        </h4>
        <div className="grid grid-cols-2 gap-2">
          <ActionButton label="Reply" icon="↩️" onClick={() => onAction('reply')} />
          <ActionButton label="Forward" icon="➡️" onClick={() => onAction('forward')} />
          <ActionButton label="Archive" icon="📥" onClick={() => onAction('archive')} />
          <ActionButton label="Snooze" icon="⏰" onClick={() => onAction('snooze')} />
          <ActionButton
            label="Mark VIP"
            icon="⭐"
            onClick={() => onAction('mark_vip')}
            variant="primary"
          />
          <ActionButton
            label="Block Sender"
            icon="🚫"
            onClick={() => onAction('block')}
            variant="danger"
          />
        </div>
      </div>

      {/* Related Context */}
      <div className="p-4 bg-[var(--bg)] border-t border-[var(--border)]">
        <h4 className="text-xs font-theme-data text-[var(--text-muted)] mb-2">Related Context</h4>
        <div className="flex flex-wrap gap-2">
          <ContextTag label="3 prior emails" />
          <ContextTag label="Slack mention" />
          <ContextTag label="Calendar invite" />
        </div>
      </div>
    </div>
  );
}

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-lg font-theme-data font-bold text-[var(--text)]">{value}</div>
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

function AnalysisItem({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: 'red' | 'yellow' | 'green' | 'cyan' | 'default';
}) {
  const colorClasses = {
    red: 'text-red-400',
    yellow: 'text-yellow-400',
    green: 'text-green-400',
    cyan: 'text-[var(--acid-cyan)]',
    default: 'text-[var(--text)]',
  };

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className={`text-xs font-theme-data ${colorClasses[color]}`}>{value}</span>
    </div>
  );
}

function ActionButton({
  label,
  icon,
  onClick,
  variant = 'default',
}: {
  label: string;
  icon: string;
  onClick: () => void;
  variant?: 'default' | 'primary' | 'danger';
}) {
  const variantClasses = {
    default: 'bg-[var(--bg)] hover:bg-[var(--surface-lighter)] border-[var(--border)]',
    primary:
      'bg-[var(--acid-green)]/10 hover:bg-[var(--acid-green)]/20 border-[var(--acid-green)]/30 text-[var(--acid-green)]',
    danger: 'bg-red-500/10 hover:bg-red-500/20 border-red-500/30 text-red-400',
  };

  return (
    <button
      onClick={onClick}
      className={`flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-theme-data border rounded transition-colors ${variantClasses[variant]}`}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function ContextTag({ label }: { label: string }) {
  return (
    <span className="px-2 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] rounded">
      {label}
    </span>
  );
}

export default SenderInsightsPanel;
