'use client';

import { useState, useMemo, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { ProviderPreferencesTab } from '@/components/settings/ProviderPreferencesTab';
import { useSWRFetch, invalidateCachePattern } from '@/hooks/useSWRFetch';
import { API_BASE_URL } from '@/config';

const SettingsPanel = dynamic(
  () => import('@/components/settings-panel').then((m) => ({ default: m.SettingsPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-[var(--surface)] rounded" />
      </div>
    ),
  },
);

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function rbacApi<T>(path: string, options?: RequestInit): Promise<T> {
  const token =
    typeof window !== 'undefined'
      ? (() => {
          try {
            return JSON.parse(localStorage.getItem('aragora_tokens') || '{}').access_token;
          } catch {
            return null;
          }
        })()
      : null;
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed (${res.status})`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Permission {
  id: string;
  name: string;
  key?: string;
  description?: string;
  resource: string;
  action: string;
}

interface Role {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  permissions: string[];
  parent?: string | null;
  parent_roles?: string[];
  is_default?: boolean;
  is_system?: boolean;
  is_custom?: boolean;
  user_count?: number;
}

interface RbacResponse {
  roles?: Role[];
  permissions?: Permission[];
}

// ---------------------------------------------------------------------------
// Role Editor Modal
// ---------------------------------------------------------------------------

interface RoleEditorProps {
  role: Role | null; // null = create mode
  allPermissions: Permission[];
  onSave: (data: {
    name: string;
    display_name: string;
    description: string;
    permissions: string[];
    base_role?: string;
  }) => Promise<void>;
  onClose: () => void;
}

function RoleEditorModal({ role, allPermissions, onSave, onClose }: RoleEditorProps) {
  const [name, setName] = useState(role?.name || '');
  const [displayName, setDisplayName] = useState(role?.display_name || '');
  const [description, setDescription] = useState(role?.description || '');
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(new Set(role?.permissions || []));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [permFilter, setPermFilter] = useState('');

  const isEdit = role !== null;

  // Group permissions by resource for the selector
  const groupedPerms = useMemo(() => {
    const map = new Map<string, Permission[]>();
    allPermissions.forEach((p) => {
      const group = map.get(p.resource) || [];
      group.push(p);
      map.set(p.resource, group);
    });
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [allPermissions]);

  const filteredGroups = useMemo(() => {
    if (!permFilter) return groupedPerms;
    const lower = permFilter.toLowerCase();
    return groupedPerms
      .map(
        ([resource, perms]) =>
          [
            resource,
            perms.filter(
              (p) =>
                p.name.toLowerCase().includes(lower) || p.resource.toLowerCase().includes(lower),
            ),
          ] as [string, Permission[]],
      )
      .filter(([, perms]) => perms.length > 0);
  }, [groupedPerms, permFilter]);

  const togglePerm = (key: string) => {
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleResource = (perms: Permission[]) => {
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      const keys = perms.map((p) => p.key || p.name);
      const allSelected = keys.every((k) => next.has(k));
      keys.forEach((k) => (allSelected ? next.delete(k) : next.add(k)));
      return next;
    });
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError('Role name is required');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave({
        name: name.trim(),
        display_name: displayName.trim() || name.trim(),
        description: description.trim(),
        permissions: Array.from(selectedPerms),
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg)] border border-[var(--acid-green)]/50 w-full max-w-2xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
          <h2 className="font-theme-data text-sm text-[var(--acid-green)]">
            {'>'} {isEdit ? 'EDIT ROLE' : 'CREATE ROLE'}
          </h2>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text)] font-theme-data text-sm"
          >
            [X]
          </button>
        </div>

        <div className="p-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-xs">
              {error}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block font-theme-data text-[10px] text-[var(--text-muted)] mb-1 uppercase">
              Role Name {isEdit && <span className="text-[var(--text-muted)]/50">(read-only)</span>}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isEdit}
              placeholder="e.g. data_analyst"
              className="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] outline-none disabled:opacity-50"
            />
          </div>

          {/* Display Name */}
          <div>
            <label className="block font-theme-data text-[10px] text-[var(--text-muted)] mb-1 uppercase">
              Display Name
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g. Data Analyst"
              className="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] outline-none"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block font-theme-data text-[10px] text-[var(--text-muted)] mb-1 uppercase">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this role is for..."
              rows={2}
              className="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] outline-none resize-none"
            />
          </div>

          {/* Permission Selector */}
          <div>
            <label className="block font-theme-data text-[10px] text-[var(--text-muted)] mb-1 uppercase">
              Permissions ({selectedPerms.size} selected)
            </label>
            <input
              type="text"
              value={permFilter}
              onChange={(e) => setPermFilter(e.target.value)}
              placeholder="Filter permissions..."
              className="w-full px-3 py-2 mb-2 bg-[var(--surface)] border border-[var(--border)] font-theme-data text-xs text-[var(--text)] focus:border-[var(--acid-green)] outline-none"
            />
            <div className="border border-[var(--border)] max-h-48 overflow-y-auto">
              {filteredGroups.map(([resource, perms]) => {
                const keys = perms.map((p) => p.key || p.name);
                const allSelected = keys.every((k) => selectedPerms.has(k));
                const someSelected = keys.some((k) => selectedPerms.has(k));
                return (
                  <div key={resource}>
                    <button
                      onClick={() => toggleResource(perms)}
                      className="w-full text-left px-3 py-1.5 bg-[var(--acid-green)]/5 font-theme-data text-[10px] text-[var(--acid-green)] uppercase tracking-wider flex items-center gap-2 hover:bg-[var(--acid-green)]/10"
                    >
                      <span className="font-theme-data">
                        {allSelected ? '[+]' : someSelected ? '[~]' : '[-]'}
                      </span>
                      {resource} ({perms.length})
                    </button>
                    {perms.map((p) => {
                      const key = p.key || p.name;
                      return (
                        <button
                          key={p.id}
                          onClick={() => togglePerm(key)}
                          className={`w-full text-left px-6 py-1 font-theme-data text-xs flex items-center gap-2 hover:bg-[var(--surface)]/50 ${
                            selectedPerms.has(key)
                              ? 'text-[var(--acid-green)]'
                              : 'text-[var(--text-muted)]'
                          }`}
                        >
                          <span>{selectedPerms.has(key) ? '[+]' : '[-]'}</span>
                          {p.name}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--border)] flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 font-theme-data text-xs text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] hover:border-[var(--text-muted)]"
          >
            CANCEL
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="px-4 py-2 font-theme-data text-xs bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 disabled:opacity-50"
          >
            {saving ? 'SAVING...' : isEdit ? 'UPDATE ROLE' : 'CREATE ROLE'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delete Confirmation Modal
// ---------------------------------------------------------------------------

function ConfirmDeleteModal({
  roleName,
  onConfirm,
  onClose,
}: {
  roleName: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await onConfirm();
      onClose();
    } catch {
      setDeleting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg)] border border-red-500/50 p-6 max-w-sm"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-theme-data text-sm text-red-400 mb-3">{'>'} DELETE ROLE</h3>
        <p className="font-theme-data text-xs text-[var(--text-muted)] mb-4">
          Are you sure you want to delete <span className="text-[var(--text)]">{roleName}</span>?
          This action cannot be undone.
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 font-theme-data text-xs text-[var(--text-muted)] border border-[var(--border)]"
          >
            CANCEL
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="px-4 py-2 font-theme-data text-xs bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
          >
            {deleting ? 'DELETING...' : 'DELETE'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RBAC Components
// ---------------------------------------------------------------------------

function RoleHierarchy({ roles }: { roles: Role[] }) {
  // Build hierarchy tree
  const rootRoles = roles.filter((r) => !r.parent);
  const childMap = useMemo(() => {
    const map = new Map<string, Role[]>();
    roles.forEach((r) => {
      if (r.parent) {
        const children = map.get(r.parent) || [];
        children.push(r);
        map.set(r.parent, children);
      }
    });
    return map;
  }, [roles]);

  const renderRole = (role: Role, depth: number) => {
    const children = childMap.get(role.name) || childMap.get(role.id) || [];
    return (
      <div key={role.id} style={{ marginLeft: depth * 24 }}>
        <div className="flex items-center gap-2 py-2 px-3 hover:bg-[var(--surface)]/50 transition-colors">
          <span className="text-[var(--acid-green)] font-theme-data text-xs">
            {depth > 0 ? '\u2514\u2500 ' : '\u25B8 '}
          </span>
          <span className="font-theme-data text-sm text-[var(--text)]">{role.name}</span>
          {role.is_default && (
            <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30">
              DEFAULT
            </span>
          )}
          <span className="text-[10px] font-theme-data text-[var(--text-muted)] ml-auto">
            {role.permissions.length} permissions
            {role.user_count !== undefined && ` | ${role.user_count} users`}
          </span>
        </div>
        {children.map((child) => renderRole(child, depth + 1))}
      </div>
    );
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} ROLE HIERARCHY</h3>
      </div>
      <div className="p-4">
        {rootRoles.length === 0 ? (
          <div className="text-center py-4 text-[var(--text-muted)] font-theme-data text-sm">
            No roles defined
          </div>
        ) : (
          rootRoles.map((role) => renderRole(role, 0))
        )}
      </div>
    </div>
  );
}

function PermissionMatrix({ roles, permissions }: { roles: Role[]; permissions: Permission[] }) {
  // Group permissions by resource
  const resources = useMemo(() => {
    const map = new Map<string, Permission[]>();
    permissions.forEach((p) => {
      const group = map.get(p.resource) || [];
      group.push(p);
      map.set(p.resource, group);
    });
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [permissions]);

  if (permissions.length === 0 || roles.length === 0) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-8 text-center">
        <div className="text-[var(--text-muted)] font-theme-data text-sm">
          No permission data available
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
      <div className="p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
          {'>'} PERMISSION MATRIX
        </h3>
        <p className="text-[10px] font-theme-data text-[var(--text-muted)] mt-1">
          {permissions.length} permissions across {resources.length} resources
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--bg)]">
              <th className="text-left p-3 font-theme-data text-[var(--text-muted)] sticky left-0 bg-[var(--bg)] min-w-[180px]">
                Permission
              </th>
              {roles.map((role) => (
                <th
                  key={role.id}
                  className="text-center p-3 font-theme-data text-[var(--text-muted)] min-w-[80px]"
                >
                  {role.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {resources.map(([resource, perms]) => (
              <>
                <tr key={`group-${resource}`} className="bg-[var(--acid-green)]/5">
                  <td
                    colSpan={roles.length + 1}
                    className="p-2 font-theme-data text-[10px] text-[var(--acid-green)] uppercase tracking-wider"
                  >
                    {resource}
                  </td>
                </tr>
                {perms.map((perm) => (
                  <tr
                    key={perm.id}
                    className="border-b border-[var(--border)]/50 hover:bg-[var(--surface)]/50"
                  >
                    <td className="p-3 font-theme-data text-[var(--text)] sticky left-0 bg-[var(--surface)]">
                      <div>{perm.name}</div>
                      {perm.description && (
                        <div className="text-[10px] text-[var(--text-muted)]">
                          {perm.description}
                        </div>
                      )}
                    </td>
                    {roles.map((role) => {
                      const hasPermission =
                        role.permissions.includes(perm.id) || role.permissions.includes(perm.name);
                      return (
                        <td key={role.id} className="p-3 text-center">
                          {hasPermission ? (
                            <span className="text-[var(--acid-green)] font-theme-data">[+]</span>
                          ) : (
                            <span className="text-[var(--text-muted)]/30 font-theme-data">[-]</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RolesList({
  roles,
  onEdit,
  onDelete,
}: {
  roles: Role[];
  onEdit: (role: Role) => void;
  onDelete: (role: Role) => void;
}) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} ROLES</h3>
      </div>
      <div className="divide-y divide-[var(--border)]">
        {roles.map((role) => (
          <div key={role.id} className="p-4 hover:bg-[var(--bg)] transition-colors group">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                  {role.display_name || role.name}
                </span>
                <span className="font-theme-data text-[10px] text-[var(--text-muted)]">
                  ({role.name})
                </span>
                {role.is_system && (
                  <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30">
                    SYSTEM
                  </span>
                )}
                {role.is_custom && (
                  <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-purple-500/10 text-purple-400 border border-purple-500/30">
                    CUSTOM
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {role.permissions.length} permissions
                </span>
                {role.is_custom && (
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                    <button
                      onClick={() => onEdit(role)}
                      className="px-2 py-0.5 text-[10px] font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/10"
                    >
                      EDIT
                    </button>
                    <button
                      onClick={() => onDelete(role)}
                      className="px-2 py-0.5 text-[10px] font-theme-data text-red-400 border border-red-400/30 hover:bg-red-400/10"
                    >
                      DEL
                    </button>
                  </div>
                )}
              </div>
            </div>
            {role.description && (
              <p className="text-xs text-[var(--text-muted)] font-theme-data mb-2">
                {role.description}
              </p>
            )}
            <div className="flex flex-wrap gap-1">
              {role.permissions.slice(0, 8).map((p) => (
                <span
                  key={p}
                  className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--bg)] text-[var(--text-muted)] border border-[var(--border)]"
                >
                  {p}
                </span>
              ))}
              {role.permissions.length > 8 && (
                <span className="px-1.5 py-0.5 text-[10px] font-theme-data text-[var(--text-muted)]">
                  +{role.permissions.length - 8} more
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type ActiveTab = 'preferences' | 'providers' | 'roles' | 'permissions' | 'hierarchy';

interface PermissionsResponse {
  permissions?: Permission[];
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('preferences');
  const [editorRole, setEditorRole] = useState<Role | null | undefined>(undefined); // undefined=closed, null=create, Role=edit
  const [deleteRole, setDeleteRole] = useState<Role | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Fetch RBAC data
  const {
    data: rbacData,
    error: rbacError,
    isLoading: rbacLoading,
    mutate: mutateRoles,
  } = useSWRFetch<RbacResponse>('/api/v1/rbac/roles?include_permissions=true', {
    refreshInterval: 120000,
  });

  // Fetch all permissions for the editor
  const { data: permData } = useSWRFetch<PermissionsResponse>('/api/v1/rbac/permissions', {
    refreshInterval: 300000,
  });

  const roles: Role[] = rbacData?.roles || [];
  const permissions: Permission[] = rbacData?.permissions || [];
  const allPermissions: Permission[] = permData?.permissions || permissions;

  const refreshRbac = useCallback(() => {
    mutateRoles();
    invalidateCachePattern(/\/rbac\//);
  }, [mutateRoles]);

  const handleCreateRole = useCallback(
    async (data: {
      name: string;
      display_name: string;
      description: string;
      permissions: string[];
    }) => {
      await rbacApi('/api/v1/rbac/roles', { method: 'POST', body: JSON.stringify(data) });
      refreshRbac();
    },
    [refreshRbac],
  );

  const handleUpdateRole = useCallback(
    async (data: {
      name: string;
      display_name: string;
      description: string;
      permissions: string[];
    }) => {
      await rbacApi(`/api/v1/rbac/roles/${encodeURIComponent(data.name)}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
      refreshRbac();
    },
    [refreshRbac],
  );

  const handleDeleteRole = useCallback(
    async (name: string) => {
      await rbacApi(`/api/v1/rbac/roles/${encodeURIComponent(name)}`, { method: 'DELETE' });
      refreshRbac();
    },
    [refreshRbac],
  );

  const tabs: { key: ActiveTab; label: string }[] = [
    { key: 'preferences', label: 'PREFERENCES' },
    { key: 'providers', label: 'PROVIDER PREFERENCES' },
    { key: 'roles', label: 'ROLES' },
    { key: 'permissions', label: 'PERMISSION MATRIX' },
    { key: 'hierarchy', label: 'HIERARCHY' },
  ];
  const showRbacSummary = activeTab !== 'preferences' && activeTab !== 'providers';

  return (
    <ProtectedRoute>
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />

        <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
          <div className="container mx-auto px-4 py-6">
            {/* Header */}
            <div className="mb-6">
              <h1 className="text-2xl font-theme-data text-[var(--acid-green)] mb-2">
                {'>'} SETTINGS & RBAC
              </h1>
              <p className="text-[var(--text-muted)] font-theme-data text-sm">
                Configure preferences, inspect provider availability, and manage roles.
              </p>
            </div>

            {/* Tab Navigation */}
            <div className="flex gap-0.5 mb-6 bg-[var(--bg)] border border-[var(--border)] p-0.5 w-fit font-theme-data text-xs">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`px-4 py-2 transition-colors ${
                    activeTab === tab.key
                      ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                      : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* RBAC Summary Stats */}
            {showRbacSummary && (
              <div className="grid grid-cols-3 gap-4 mb-6">
                <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                  <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                    {rbacLoading ? '-' : roles.length}
                  </div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)]">Roles</div>
                </div>
                <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                  <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                    {rbacLoading ? '-' : permissions.length}
                  </div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    Permissions
                  </div>
                </div>
                <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                  <div className="text-2xl font-theme-data text-purple-400">
                    {rbacLoading ? '-' : new Set(permissions.map((p) => p.resource)).size}
                  </div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    Resources
                  </div>
                </div>
              </div>
            )}

            {/* Error State for RBAC */}
            {rbacError && showRbacSummary && (
              <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
                Failed to load RBAC data. The backend may be unavailable.
              </div>
            )}

            {/* Tab Content */}
            {activeTab === 'preferences' && (
              <PanelErrorBoundary panelName="Settings">
                <SettingsPanel />
              </PanelErrorBoundary>
            )}

            {activeTab === 'providers' && (
              <PanelErrorBoundary panelName="Provider Preferences">
                <ProviderPreferencesTab />
              </PanelErrorBoundary>
            )}

            {activeTab === 'roles' && (
              <PanelErrorBoundary panelName="Roles">
                {actionError && (
                  <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-xs flex items-center justify-between">
                    <span>{actionError}</span>
                    <button
                      onClick={() => setActionError(null)}
                      className="text-red-400 hover:text-red-300"
                    >
                      [X]
                    </button>
                  </div>
                )}
                <div className="mb-4">
                  <button
                    onClick={() => setEditorRole(null)}
                    className="px-4 py-2 font-theme-data text-xs bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80"
                  >
                    + CREATE ROLE
                  </button>
                </div>
                {rbacLoading ? (
                  <div className="animate-pulse space-y-3">
                    {[...Array(4)].map((_, i) => (
                      <div key={i} className="h-20 bg-[var(--surface)] rounded" />
                    ))}
                  </div>
                ) : (
                  <RolesList
                    roles={roles}
                    onEdit={(role) => setEditorRole(role)}
                    onDelete={(role) => setDeleteRole(role)}
                  />
                )}
              </PanelErrorBoundary>
            )}

            {activeTab === 'permissions' && (
              <PanelErrorBoundary panelName="Permission Matrix">
                {rbacLoading ? (
                  <div className="animate-pulse">
                    <div className="h-96 bg-[var(--surface)] rounded" />
                  </div>
                ) : (
                  <PermissionMatrix roles={roles} permissions={permissions} />
                )}
              </PanelErrorBoundary>
            )}

            {activeTab === 'hierarchy' && (
              <PanelErrorBoundary panelName="Role Hierarchy">
                {rbacLoading ? (
                  <div className="animate-pulse">
                    <div className="h-48 bg-[var(--surface)] rounded" />
                  </div>
                ) : (
                  <RoleHierarchy roles={roles} />
                )}
              </PanelErrorBoundary>
            )}
          </div>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
            <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
              {'='.repeat(40)}
            </div>
            <p className="text-[var(--text-muted)]">{'>'} ARAGORA // SETTINGS & RBAC</p>
          </footer>
        </main>

        {/* Role Editor Modal */}
        {editorRole !== undefined && (
          <RoleEditorModal
            role={editorRole}
            allPermissions={allPermissions}
            onSave={editorRole ? handleUpdateRole : handleCreateRole}
            onClose={() => setEditorRole(undefined)}
          />
        )}

        {/* Delete Confirmation Modal */}
        {deleteRole && (
          <ConfirmDeleteModal
            roleName={deleteRole.name}
            onConfirm={async () => {
              try {
                await handleDeleteRole(deleteRole.name);
                setDeleteRole(null);
              } catch (e) {
                setActionError(e instanceof Error ? e.message : 'Delete failed');
                setDeleteRole(null);
              }
            }}
            onClose={() => setDeleteRole(null)}
          />
        )}
      </>
    </ProtectedRoute>
  );
}
