'use client';

import { useState } from 'react';
import type { Workspace, WorkspaceMember } from './WorkspaceManager';
import { useWorkspaceInvites, type WorkspaceInvite } from '@/hooks/useWorkspaceInvites';

export interface TeamAccessPanelProps {
  workspace: Workspace;
  onMemberAdd?: (email: string, role: WorkspaceMember['role']) => void;
  onMemberRemove?: (memberId: string) => void;
  onRoleChange?: (memberId: string, role: WorkspaceMember['role']) => void;
  className?: string;
}

const ROLE_OPTIONS: { value: WorkspaceMember['role']; label: string; description: string }[] = [
  { value: 'admin', label: 'Admin', description: 'Full access, can manage members' },
  { value: 'member', label: 'Member', description: 'Can view and edit content' },
  { value: 'viewer', label: 'Viewer', description: 'Read-only access' },
];

export function TeamAccessPanel({
  workspace,
  onMemberAdd,
  onMemberRemove,
  onRoleChange,
  className = '',
}: TeamAccessPanelProps) {
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<WorkspaceMember['role']>('member');
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch pending invites
  const {
    invites,
    isLoading: invitesLoading,
    createInvite,
    cancelInvite,
    resendInvite,
  } = useWorkspaceInvites(workspace.id, 'pending');

  const getRoleColor = (role: WorkspaceMember['role']) => {
    switch (role) {
      case 'owner':
        return 'bg-[var(--accent)]/20 text-[var(--accent)]';
      case 'admin':
        return 'bg-cyan-400/20 text-cyan-400';
      case 'member':
        return 'bg-purple-400/20 text-purple-400';
      case 'viewer':
        return 'bg-gray-400/20 text-gray-400';
    }
  };

  const formatLastActive = (dateStr?: string) => {
    if (!dateStr) return 'Never';
    const diff = Date.now() - new Date(dateStr).getTime();
    const hours = Math.floor(diff / 3600000);
    if (hours < 1) return 'Just now';
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(dateStr).toLocaleDateString();
  };

  const formatExpiration = (dateStr: string) => {
    const diff = new Date(dateStr).getTime() - Date.now();
    const days = Math.floor(diff / 86400000);
    if (days < 0) return 'Expired';
    if (days === 0) return 'Expires today';
    if (days === 1) return 'Expires tomorrow';
    return `Expires in ${days} days`;
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail) return;

    setIsSubmitting(true);
    setInviteError(null);

    try {
      await createInvite({ email: inviteEmail, role: inviteRole });

      // Also call the parent callback if provided
      onMemberAdd?.(inviteEmail, inviteRole);

      setInviteEmail('');
      setInviteRole('member');
      setShowInviteModal(false);
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : 'Failed to send invite');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancelInvite = async (invite: WorkspaceInvite) => {
    try {
      await cancelInvite(invite.id);
    } catch (err) {
      console.error('Failed to cancel invite:', err);
    }
  };

  const handleResendInvite = async (invite: WorkspaceInvite) => {
    try {
      await resendInvite(invite.id);
    } catch (err) {
      console.error('Failed to resend invite:', err);
    }
  };

  return (
    <div className={className}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h4 className="font-theme-data font-bold text-text">Team Members</h4>
          <p className="text-xs text-text-muted mt-1">
            {workspace.members.length} members in this workspace
          </p>
        </div>
        <button
          onClick={() => setShowInviteModal(true)}
          className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
        >
          + INVITE
        </button>
      </div>

      {/* Members List */}
      <div className="space-y-2">
        {workspace.members.map((member) => (
          <div
            key={member.id}
            className="p-4 bg-bg border border-border rounded-lg flex items-center gap-4"
          >
            {/* Avatar */}
            <div className="w-10 h-10 rounded-full bg-surface flex items-center justify-center font-theme-data font-bold text-[var(--accent)]">
              {member.name.charAt(0).toUpperCase()}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-theme-data font-bold text-text truncate">{member.name}</span>
                <span
                  className={`px-2 py-0.5 text-xs font-theme-data uppercase rounded ${getRoleColor(member.role)}`}
                >
                  {member.role}
                </span>
              </div>
              <div className="text-xs text-text-muted mt-0.5 truncate">{member.email}</div>
            </div>

            {/* Last Active */}
            <div className="text-right text-xs">
              <div className="text-text-muted">Last active</div>
              <div className="font-theme-data text-text">{formatLastActive(member.lastActive)}</div>
            </div>

            {/* Actions */}
            {member.role !== 'owner' && (
              <div className="flex items-center gap-2">
                <select
                  value={member.role}
                  onChange={(e) =>
                    onRoleChange?.(member.id, e.target.value as WorkspaceMember['role'])
                  }
                  className="px-2 py-1 text-xs font-theme-data bg-surface border border-border rounded focus:outline-none focus:border-[var(--accent)]"
                >
                  {ROLE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => onMemberRemove?.(member.id)}
                  className="p-1.5 text-xs text-red-400 hover:bg-red-900/20 rounded transition-colors"
                  title="Remove member"
                >
                  &#x2715;
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Pending Invites */}
      <div className="mt-6">
        <div className="flex items-center justify-between mb-3">
          <h4 className="font-theme-data font-bold text-text">Pending Invites</h4>
          {invites.length > 0 && (
            <span className="px-2 py-0.5 text-xs font-theme-data bg-yellow-500/20 text-yellow-400 rounded">
              {invites.length} pending
            </span>
          )}
        </div>

        {invitesLoading ? (
          <div className="p-4 bg-bg border border-border rounded-lg text-center">
            <span className="text-sm text-text-muted">Loading invites...</span>
          </div>
        ) : invites.length === 0 ? (
          <div className="p-4 bg-bg border border-border rounded-lg text-center">
            <span className="text-sm text-text-muted">No pending invites</span>
          </div>
        ) : (
          <div className="space-y-2">
            {invites.map((invite) => (
              <div
                key={invite.id}
                className="p-4 bg-bg border border-yellow-500/30 rounded-lg flex items-center gap-4"
              >
                {/* Email Icon */}
                <div className="w-10 h-10 rounded-full bg-yellow-500/10 flex items-center justify-center text-yellow-400">
                  @
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-theme-data text-text truncate">{invite.email}</span>
                    <span
                      className={`px-2 py-0.5 text-xs font-theme-data uppercase rounded ${getRoleColor(invite.role)}`}
                    >
                      {invite.role}
                    </span>
                  </div>
                  <div className="text-xs text-text-muted mt-0.5">
                    {formatExpiration(invite.expires_at)}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleResendInvite(invite)}
                    className="px-2 py-1 text-xs font-theme-data text-cyan-400 hover:bg-cyan-400/10 border border-cyan-400/30 rounded transition-colors"
                    title="Resend invite"
                  >
                    RESEND
                  </button>
                  <button
                    onClick={() => handleCancelInvite(invite)}
                    className="p-1.5 text-xs text-red-400 hover:bg-red-900/20 rounded transition-colors"
                    title="Cancel invite"
                  >
                    &#x2715;
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Role Permissions Legend */}
      <div className="mt-6 p-4 bg-bg border border-border rounded-lg">
        <h4 className="font-theme-data text-xs text-text-muted mb-3">ROLE PERMISSIONS</h4>
        <div className="space-y-2">
          {[
            { role: 'owner', perms: ['Full access', 'Delete workspace', 'Transfer ownership'] },
            { role: 'admin', perms: ['Manage members', 'Edit settings', 'Full content access'] },
            { role: 'member', perms: ['Create & edit content', 'Run workflows', 'View analytics'] },
            { role: 'viewer', perms: ['View content', 'View analytics'] },
          ].map(({ role, perms }) => (
            <div key={role} className="flex items-start gap-3">
              <span
                className={`px-2 py-0.5 text-xs font-theme-data uppercase rounded ${getRoleColor(role as WorkspaceMember['role'])}`}
              >
                {role}
              </span>
              <span className="text-xs text-text-muted">{perms.join(' | ')}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-bg/80 flex items-center justify-center z-50">
          <div className="bg-surface border border-border rounded-lg p-6 w-full max-w-md">
            <h3 className="font-theme-data font-bold text-[var(--accent)] mb-4">INVITE MEMBER</h3>
            <form onSubmit={handleInvite}>
              <div className="space-y-4">
                {inviteError && (
                  <div className="p-3 bg-red-900/20 border border-red-500/30 rounded text-xs text-red-400">
                    {inviteError}
                  </div>
                )}
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-1">
                    EMAIL ADDRESS
                  </label>
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    required
                    disabled={isSubmitting}
                    className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] disabled:opacity-50"
                    placeholder="colleague@company.com"
                  />
                </div>
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-1">ROLE</label>
                  <div className="space-y-2">
                    {ROLE_OPTIONS.map((option) => (
                      <label
                        key={option.value}
                        className={`
                          flex items-start gap-3 p-3 bg-bg border rounded-lg cursor-pointer transition-all
                          ${inviteRole === option.value ? 'border-[var(--accent)]' : 'border-border hover:border-text-muted'}
                          ${isSubmitting ? 'opacity-50 cursor-not-allowed' : ''}
                        `}
                      >
                        <input
                          type="radio"
                          name="role"
                          value={option.value}
                          checked={inviteRole === option.value}
                          onChange={(e) => setInviteRole(e.target.value as WorkspaceMember['role'])}
                          disabled={isSubmitting}
                          className="mt-0.5"
                        />
                        <div>
                          <div className="font-theme-data text-sm text-text">{option.label}</div>
                          <div className="text-xs text-text-muted">{option.description}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              <div className="flex gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => {
                    setShowInviteModal(false);
                    setInviteError(null);
                  }}
                  disabled={isSubmitting}
                  className="flex-1 px-4 py-2 text-xs font-theme-data border border-border rounded hover:border-text-muted transition-colors disabled:opacity-50"
                >
                  CANCEL
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex-1 px-4 py-2 text-xs font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
                >
                  {isSubmitting ? 'SENDING...' : 'SEND INVITE'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
