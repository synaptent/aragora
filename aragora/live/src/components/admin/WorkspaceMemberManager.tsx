'use client';

import React, { useState, useCallback } from 'react';
import { MemberTable, Member, Column } from './MemberTable';

export interface WorkspaceMember extends Member {
  workspaceId: string;
  permissions: string[];
  invitedBy?: string;
  invitedAt?: string;
}

export interface WorkspaceRole {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  isDefault?: boolean;
}

interface WorkspaceMemberManagerProps {
  workspaceId: string;
  members: WorkspaceMember[];
  roles: WorkspaceRole[];
  loading?: boolean;
  onRoleChange?: (memberId: string, newRole: string) => Promise<void>;
  onInvite?: (email: string, role: string) => Promise<void>;
  onRemove?: (memberId: string) => Promise<void>;
  onBulkAction?: (action: string, memberIds: string[]) => Promise<void>;
  className?: string;
}

function RoleSelector({
  currentRole,
  roles,
  onChange,
  disabled = false,
}: {
  currentRole: string;
  roles: WorkspaceRole[];
  onChange: (role: string) => void;
  disabled?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={`px-3 py-1.5 font-theme-data text-xs rounded border transition-colors ${
          disabled
            ? 'bg-surface-elevated/50 text-text-muted border-[var(--accent)]/10 cursor-not-allowed'
            : 'bg-surface-elevated text-text border-[var(--accent)]/30 hover:border-[var(--accent)]/60'
        }`}
      >
        {currentRole.toUpperCase()}{' '}
        {!disabled && <span className="ml-1 text-[var(--acid-cyan)]">v</span>}
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-50 bg-surface border border-[var(--accent)]/40 rounded shadow-lg py-1 min-w-[180px]">
            {roles.map((role) => (
              <button
                key={role.id}
                onClick={() => {
                  onChange(role.id);
                  setIsOpen(false);
                }}
                className={`w-full text-left px-3 py-2 font-theme-data text-xs transition-colors hover:bg-surface-elevated ${
                  currentRole === role.id ? 'text-[var(--accent)]' : 'text-text'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span>{role.name.toUpperCase()}</span>
                  {role.isDefault && (
                    <span className="text-[var(--acid-cyan)] text-[10px]">DEFAULT</span>
                  )}
                </div>
                <div className="text-text-muted text-[10px] mt-0.5">{role.description}</div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function InviteModal({
  roles,
  onInvite,
  onClose,
}: {
  roles: WorkspaceRole[];
  onInvite: (email: string, role: string) => Promise<void>;
  onClose: () => void;
}) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState(roles.find((r) => r.isDefault)?.id || roles[0]?.id || 'member');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;

    setSending(true);
    setError(null);
    try {
      await onInvite(email.trim(), role);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send invite');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-background/80" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md card p-6">
        <h3 className="font-theme-data text-lg text-[var(--accent)] mb-4">INVITE MEMBER</h3>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block font-theme-data text-xs text-text-muted mb-2">
              EMAIL ADDRESS
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="colleague@example.com"
              className="w-full px-3 py-2 bg-surface-elevated border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text placeholder-text-muted focus:border-[var(--accent)] focus:outline-none"
              autoFocus
            />
          </div>
          <div className="mb-6">
            <label className="block font-theme-data text-xs text-text-muted mb-2">ROLE</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full px-3 py-2 bg-surface-elevated border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
            >
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} - {r.description}
                </option>
              ))}
            </select>
          </div>
          {error && (
            <div className="mb-4 px-3 py-2 bg-acid-red/10 border border-acid-red/40 rounded font-theme-data text-xs text-acid-red">
              {error}
            </div>
          )}
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
            >
              CANCEL
            </button>
            <button
              type="submit"
              disabled={sending || !email.trim()}
              className="px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40 rounded hover:bg-[var(--accent)]/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {sending ? 'SENDING...' : 'SEND INVITE'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function WorkspaceMemberManager({
  workspaceId: _workspaceId,
  members,
  roles,
  loading = false,
  onRoleChange,
  onInvite,
  onRemove,
  onBulkAction,
  className = '',
}: WorkspaceMemberManagerProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showInvite, setShowInvite] = useState(false);
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());

  const handleRoleChange = useCallback(
    async (memberId: string, newRole: string) => {
      if (!onRoleChange) return;

      setProcessingIds((prev) => new Set(prev).add(memberId));
      try {
        await onRoleChange(memberId, newRole);
      } finally {
        setProcessingIds((prev) => {
          const next = new Set(prev);
          next.delete(memberId);
          return next;
        });
      }
    },
    [onRoleChange],
  );

  const handleAction = useCallback(
    async (action: string, member: WorkspaceMember) => {
      if (action === 'remove' && onRemove) {
        if (confirm(`Remove ${member.name || member.email} from workspace?`)) {
          setProcessingIds((prev) => new Set(prev).add(member.id));
          try {
            await onRemove(member.id);
          } finally {
            setProcessingIds((prev) => {
              const next = new Set(prev);
              next.delete(member.id);
              return next;
            });
          }
        }
      }
    },
    [onRemove],
  );

  const handleBulkAction = useCallback(
    async (action: string) => {
      if (!onBulkAction || selectedIds.length === 0) return;

      if (action === 'remove') {
        if (!confirm(`Remove ${selectedIds.length} member(s) from workspace?`)) return;
      }

      selectedIds.forEach((id) => setProcessingIds((prev) => new Set(prev).add(id)));
      try {
        await onBulkAction(action, selectedIds);
        setSelectedIds([]);
      } finally {
        setProcessingIds(new Set());
      }
    },
    [onBulkAction, selectedIds],
  );

  const columns: Column<WorkspaceMember>[] = [
    {
      key: 'name',
      label: 'Member',
      sortable: true,
      render: (_, row) => (
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-[var(--accent)]/20 flex items-center justify-center font-theme-data text-[var(--accent)] text-sm">
            {row.name?.charAt(0).toUpperCase() || row.email?.charAt(0).toUpperCase() || '?'}
          </div>
          <div>
            <div className="font-theme-data text-sm text-text">{row.name || 'Unknown'}</div>
            <div className="font-theme-data text-xs text-[var(--acid-cyan)]">{row.email}</div>
          </div>
        </div>
      ),
    },
    {
      key: 'role',
      label: 'Role',
      sortable: true,
      width: '180px',
      render: (value, row) => (
        <RoleSelector
          currentRole={value as string}
          roles={roles}
          onChange={(newRole) => handleRoleChange(row.id, newRole)}
          disabled={processingIds.has(row.id) || row.role === 'owner'}
        />
      ),
    },
    {
      key: 'status',
      label: 'Status',
      sortable: true,
      width: '100px',
      render: (value) => {
        const status = value as 'active' | 'inactive' | 'pending';
        const colors: Record<string, string> = {
          active: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
          inactive: 'bg-acid-red/20 text-acid-red border-acid-red/40',
          pending: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
        };
        return (
          <span className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status]}`}>
            {status.toUpperCase()}
          </span>
        );
      },
    },
    {
      key: 'joinedAt',
      label: 'Joined',
      sortable: true,
      width: '120px',
      render: (value) => (
        <span className="font-theme-data text-xs text-text-muted">
          {value ? new Date(value as string).toLocaleDateString() : '-'}
        </span>
      ),
    },
  ];

  return (
    <div className={className}>
      {/* Header Actions */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <h2 className="font-theme-data text-lg text-[var(--accent)]">WORKSPACE MEMBERS</h2>
          <span className="font-theme-data text-sm text-text-muted">
            {members.length} member{members.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.length > 0 && onBulkAction && (
            <div className="flex items-center gap-2 mr-4">
              <span className="font-theme-data text-xs text-text-muted">
                {selectedIds.length} selected
              </span>
              <button
                onClick={() => handleBulkAction('deactivate')}
                className="px-3 py-1.5 font-theme-data text-xs text-[var(--acid-yellow)] border border-acid-yellow/40 rounded hover:bg-acid-yellow/10 transition-colors"
              >
                DEACTIVATE
              </button>
              <button
                onClick={() => handleBulkAction('remove')}
                className="px-3 py-1.5 font-theme-data text-xs text-acid-red border border-acid-red/40 rounded hover:bg-acid-red/10 transition-colors"
              >
                REMOVE
              </button>
            </div>
          )}
          {onInvite && (
            <button
              onClick={() => setShowInvite(true)}
              className="px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40 rounded hover:bg-[var(--accent)]/30 transition-colors"
            >
              + INVITE
            </button>
          )}
        </div>
      </div>

      {/* Member Table */}
      <MemberTable<WorkspaceMember>
        data={members}
        columns={columns}
        loading={loading}
        selectable={!!onBulkAction}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
        actions={[
          { label: 'View Details', value: 'view' },
          { label: 'Remove', value: 'remove', variant: 'danger' },
        ]}
        onAction={handleAction}
      />

      {/* Invite Modal */}
      {showInvite && onInvite && (
        <InviteModal roles={roles} onInvite={onInvite} onClose={() => setShowInvite(false)} />
      )}
    </div>
  );
}

export default WorkspaceMemberManager;
