'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { MemberTable, Member, Column } from '@/components/admin/MemberTable';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface User extends Member {
  org_id?: string;
  org_name?: string;
  email_verified: boolean;
  created_at: string;
  last_login_at?: string;
}

interface UsersResponse {
  users: Array<{
    id: string;
    email: string;
    name: string;
    org_id?: string;
    role: string;
    is_active: boolean;
    email_verified: boolean;
    created_at: string;
    last_login_at?: string;
  }>;
  total: number;
  limit: number;
  offset: number;
}

// Invite User Modal
function InviteUserModal({
  isOpen,
  onClose,
  onInvite,
}: {
  isOpen: boolean;
  onClose: () => void;
  onInvite: (email: string, role: string) => Promise<void>;
}) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('member');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await onInvite(email, role);
      setEmail('');
      setRole('member');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to invite user');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-surface border border-[var(--accent)]/40 rounded-lg shadow-xl w-full max-w-md p-6 z-10">
        <h2 className="font-theme-data text-lg text-[var(--accent)] mb-4">Invite User</h2>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label className="block font-theme-data text-xs text-text-muted mb-2">
                Email Address
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full bg-bg border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2 focus:outline-none focus:border-[var(--accent)]"
                placeholder="user@example.com"
              />
            </div>
            <div>
              <label className="block font-theme-data text-xs text-text-muted mb-2">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full bg-bg border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2 focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="viewer">Viewer</option>
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            {error && (
              <div className="p-3 bg-acid-red/10 border border-acid-red/40 rounded">
                <p className="font-theme-data text-xs text-acid-red">{error}</p>
              </div>
            )}
          </div>
          <div className="flex gap-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-[var(--accent)]/40 text-text-muted font-theme-data text-sm rounded hover:bg-surface-elevated transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Inviting...' : 'Send Invite'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Change Role Modal
function ChangeRoleModal({
  isOpen,
  onClose,
  user,
  onChangeRole,
}: {
  isOpen: boolean;
  onClose: () => void;
  user: User | null;
  onChangeRole: (userId: string, newRole: string) => Promise<void>;
}) {
  const [role, setRole] = useState(user?.role || 'member');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) setRole(user.role);
  }, [user]);

  if (!isOpen || !user) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await onChangeRole(user.id, role);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change role');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-surface border border-[var(--accent)]/40 rounded-lg shadow-xl w-full max-w-md p-6 z-10">
        <h2 className="font-theme-data text-lg text-[var(--accent)] mb-4">Change Role</h2>
        <p className="font-theme-data text-sm text-text-muted mb-4">
          Changing role for: <span className="text-[var(--acid-cyan)]">{user.email}</span>
        </p>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label className="block font-theme-data text-xs text-text-muted mb-2">New Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full bg-bg border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2 focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="viewer">Viewer</option>
                <option value="member">Member</option>
                <option value="admin">Admin</option>
                <option value="owner">Owner</option>
              </select>
            </div>
            {error && (
              <div className="p-3 bg-acid-red/10 border border-acid-red/40 rounded">
                <p className="font-theme-data text-xs text-acid-red">{error}</p>
              </div>
            )}
          </div>
          <div className="flex gap-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-[var(--accent)]/40 text-text-muted font-theme-data text-sm rounded hover:bg-surface-elevated transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || role === user.role}
              className="flex-1 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Updating...' : 'Update Role'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function UsersAdminPageContent() {
  const { config: backendConfig } = useBackend();
  const { user: currentUser, isAuthenticated, tokens } = useAuth();
  const searchParams = useSearchParams();
  const token = tokens?.access_token;

  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [roleFilter, setRoleFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showInviteModal, setShowInviteModal] = useState(searchParams.get('action') === 'invite');
  const [showRoleModal, setShowRoleModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  const limit = 20;

  const fetchUsers = useCallback(async () => {
    if (!token) return;

    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams({
        limit: String(limit),
        offset: String((page - 1) * limit),
      });
      if (roleFilter) params.set('role', roleFilter);
      if (statusFilter === 'active') params.set('active_only', 'true');
      if (statusFilter === 'inactive') params.set('inactive_only', 'true');
      if (searchQuery) params.set('search', searchQuery);

      const res = await fetch(`${backendConfig.api}/api/v1/admin/users?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        if (res.status === 403) throw new Error('Admin access required');
        throw new Error(`Failed to fetch users: ${res.status}`);
      }

      const data: UsersResponse = await res.json();
      setUsers(
        data.users.map((u) => ({
          id: u.id,
          name: u.name || u.email.split('@')[0],
          email: u.email,
          role: u.role,
          status: u.is_active ? 'active' : 'inactive',
          joinedAt: u.created_at,
          lastActive: u.last_login_at,
          org_id: u.org_id,
          email_verified: u.email_verified,
          created_at: u.created_at,
          last_login_at: u.last_login_at,
        })),
      );
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch users');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token, page, roleFilter, statusFilter, searchQuery]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchUsers();
    }
  }, [fetchUsers, isAuthenticated]);

  const handleToggleActive = async (userId: string, currentlyActive: boolean) => {
    if (!token) return;

    try {
      const action = currentlyActive ? 'deactivate' : 'activate';
      const res = await fetch(`${backendConfig.api}/api/v1/admin/users/${userId}/${action}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error(`Failed to ${action} user`);
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    }
  };

  const handleBulkAction = async (action: string) => {
    if (!token || selectedIds.length === 0) return;

    try {
      setLoading(true);
      for (const id of selectedIds) {
        const res = await fetch(`${backendConfig.api}/api/v1/admin/users/${id}/${action}`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`Failed to ${action} user ${id}`);
      }
      setSelectedIds([]);
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk action failed');
    } finally {
      setLoading(false);
    }
  };

  const handleInviteUser = async (email: string, role: string) => {
    if (!token) throw new Error('Not authenticated');

    const res = await fetch(`${backendConfig.api}/api/v1/admin/users/invite`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, role }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to send invite');
    }

    fetchUsers();
  };

  const handleChangeRole = async (userId: string, newRole: string) => {
    if (!token) throw new Error('Not authenticated');

    const res = await fetch(`${backendConfig.api}/api/v1/admin/users/${userId}/role`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: newRole }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to change role');
    }

    fetchUsers();
  };

  const handleAction = (action: string, user: User) => {
    switch (action) {
      case 'edit':
      case 'change-role':
        setSelectedUser(user);
        setShowRoleModal(true);
        break;
      case 'deactivate':
        if (user.id !== currentUser?.id) {
          handleToggleActive(user.id, user.status === 'active');
        }
        break;
      case 'activate':
        handleToggleActive(user.id, user.status === 'active');
        break;
    }
  };

  const columns: Column<User>[] = [
    {
      key: 'name',
      label: 'User',
      sortable: true,
      render: (_, row) => (
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-[var(--accent)]/20 flex items-center justify-center font-theme-data text-[var(--accent)] text-sm">
            {row.name?.charAt(0).toUpperCase() || '?'}
          </div>
          <div>
            <div className="font-theme-data text-sm text-text">{row.name}</div>
            <div className="font-theme-data text-xs text-[var(--acid-cyan)]">{row.email}</div>
          </div>
        </div>
      ),
    },
    { key: 'role', label: 'Role', sortable: true, width: '100px' },
    { key: 'status', label: 'Status', sortable: true, width: '100px' },
    {
      key: 'email_verified',
      label: 'Verified',
      render: (value) => (
        <span
          className={`font-theme-data text-xs ${value ? 'text-[var(--accent)]' : 'text-text-muted'}`}
        >
          {value ? 'YES' : 'NO'}
        </span>
      ),
      width: '80px',
    },
    {
      key: 'joinedAt',
      label: 'Joined',
      sortable: true,
      render: (value) => (
        <span className="font-theme-data text-xs text-text-muted">
          {value ? new Date(value as string).toLocaleDateString() : '-'}
        </span>
      ),
      width: '100px',
    },
    {
      key: 'lastActive',
      label: 'Last Login',
      sortable: true,
      render: (value) => (
        <span className="font-theme-data text-xs text-text-muted">
          {value ? new Date(value as string).toLocaleDateString() : 'Never'}
        </span>
      ),
      width: '100px',
    },
  ];

  const isAdmin =
    isAuthenticated && (currentUser?.role === 'admin' || currentUser?.role === 'owner');

  return (
    <AdminLayout
      title="User Management"
      description="Manage user accounts, roles, and access permissions."
      actions={
        <div className="flex items-center gap-2">
          {selectedIds.length > 0 && (
            <div className="flex items-center gap-2 mr-4">
              <span className="font-theme-data text-xs text-text-muted">
                {selectedIds.length} selected
              </span>
              <button
                onClick={() => handleBulkAction('deactivate')}
                className="px-3 py-1.5 bg-acid-red/20 border border-acid-red/40 text-acid-red font-theme-data text-xs rounded hover:bg-acid-red/30 transition-colors"
              >
                Deactivate
              </button>
              <button
                onClick={() => setSelectedIds([])}
                className="px-3 py-1.5 border border-[var(--accent)]/40 text-text-muted font-theme-data text-xs rounded hover:bg-surface-elevated transition-colors"
              >
                Clear
              </button>
            </div>
          )}
          <button
            onClick={() => setShowInviteModal(true)}
            className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
          >
            + Invite User
          </button>
        </div>
      }
    >
      {error && (
        <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
          <p className="text-acid-red font-theme-data text-sm">{error}</p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <div className="flex-1 min-w-0 sm:min-w-[200px]">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search by name or email..."
            className="w-full bg-surface border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2 focus:outline-none focus:border-[var(--accent)]"
          />
        </div>
        <select
          value={roleFilter}
          onChange={(e) => {
            setRoleFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by role"
          className="bg-surface border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2"
        >
          <option value="">All Roles</option>
          <option value="owner">Owner</option>
          <option value="admin">Admin</option>
          <option value="member">Member</option>
          <option value="viewer">Viewer</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by status"
          className="bg-surface border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2"
        >
          <option value="">All Status</option>
          <option value="active">Active Only</option>
          <option value="inactive">Inactive Only</option>
        </select>
        <button
          onClick={fetchUsers}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Total Users</div>
          <div className="font-theme-data text-2xl text-[var(--accent)]">{total}</div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Filtered</div>
          <div className="font-theme-data text-2xl text-text">{users.length}</div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Active</div>
          <div className="font-theme-data text-2xl text-[var(--acid-cyan)]">
            {users.filter((u) => u.status === 'active').length}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Selected</div>
          <div className="font-theme-data text-2xl text-[var(--acid-yellow)]">
            {selectedIds.length}
          </div>
        </div>
      </div>

      {/* Users Table */}
      <MemberTable
        data={users}
        columns={columns}
        loading={loading}
        pageSize={limit}
        currentPage={page}
        totalItems={total}
        onPageChange={setPage}
        selectable={isAdmin}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
        onAction={handleAction}
        actions={[
          { label: 'Change Role', value: 'change-role' },
          { label: 'Deactivate', value: 'deactivate', variant: 'danger' },
        ]}
      />

      {/* Modals */}
      <InviteUserModal
        isOpen={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        onInvite={handleInviteUser}
      />

      <ChangeRoleModal
        isOpen={showRoleModal}
        onClose={() => {
          setShowRoleModal(false);
          setSelectedUser(null);
        }}
        user={selectedUser}
        onChangeRole={handleChangeRole}
      />
    </AdminLayout>
  );
}

export default function UsersAdminPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-center font-theme-data text-text-muted">Loading...</div>}
    >
      <UsersAdminPageContent />
    </Suspense>
  );
}
