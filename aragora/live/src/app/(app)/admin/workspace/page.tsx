'use client';

import React, { useState, useMemo, useCallback } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import {
  WorkspaceMemberManager,
  WorkspaceMember,
  WorkspaceRole,
} from '@/components/admin/WorkspaceMemberManager';
import { RoleMatrixViewer, Role, Permission } from '@/components/admin/RoleMatrixViewer';
import {
  CostBreakdownChart,
  CostItem,
  BreakdownType,
  TimeRange,
} from '@/components/admin/CostBreakdownChart';
import { useAuthenticatedFetch, useAuthFetch } from '@/hooks/useAuthenticatedFetch';
import { useAuth } from '@/context/AuthContext';

// ============================================================================
// Types for API responses
// ============================================================================

interface RBACRole {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  is_default?: boolean;
  is_builtin?: boolean;
  parent_role?: string;
}

interface RBACPermission {
  id: string;
  resource: string;
  action: string;
  description: string;
}

interface WorkspaceMemberResponse {
  id: string;
  user_id: string;
  name?: string;
  email?: string;
  role: string;
  status: 'active' | 'pending' | 'inactive';
  joined_at: string;
  permissions: string[];
}

interface CostDataResponse {
  items: Array<{ id: string; label: string; cost: number; category: string; subcategory?: string }>;
  total: number;
  period: string;
}

interface WorkspaceSettings {
  name: string;
  description: string;
  default_role: string;
  allow_self_signup: boolean;
  max_members: number;
  require_mfa: boolean;
  debate_approval_required: boolean;
}

interface ActivityEvent {
  id: string;
  type: string;
  actor: string;
  description: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

interface PendingInvite {
  id: string;
  email: string;
  role: string;
  invited_by: string;
  invited_at: string;
  expires_at: string;
}

type Tab = 'members' | 'roles' | 'costs' | 'settings' | 'activity';

export default function WorkspaceAdminPage() {
  const [activeTab, setActiveTab] = useState<Tab>('members');
  const [breakdownType, setBreakdownType] = useState<BreakdownType>('feature');
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [settingsForm, setSettingsForm] = useState<WorkspaceSettings | null>(null);

  const { organization } = useAuth();
  const { authFetch } = useAuthFetch();

  // Fetch workspace ID from current context
  const workspaceId = organization?.id || 'default';

  // =========================================================================
  // API Data Fetching
  // =========================================================================

  // Fetch workspace members
  const {
    data: membersData,
    loading: membersLoading,
    error: membersError,
    refetch: refetchMembers,
  } = useAuthenticatedFetch<{ members: WorkspaceMemberResponse[] }>(
    `/api/v1/workspaces/${workspaceId}/members`,
    { defaultData: { members: [] } },
  );

  // Fetch RBAC roles
  const {
    data: rolesData,
    loading: rolesLoading,
    error: rolesError,
  } = useAuthenticatedFetch<{ roles: RBACRole[] }>('/api/v1/rbac/roles', {
    defaultData: { roles: [] },
  });

  // Fetch RBAC permissions
  const { data: permissionsData, loading: permissionsLoading } = useAuthenticatedFetch<{
    permissions: RBACPermission[];
  }>('/api/v1/rbac/permissions', { defaultData: { permissions: [] } });

  // Fetch cost breakdown
  const { data: costData, loading: costLoading } = useAuthenticatedFetch<CostDataResponse>(
    `/api/v1/billing/costs?workspace_id=${workspaceId}&period=${timeRange}`,
    { defaultData: { items: [], total: 0, period: timeRange }, deps: [timeRange, workspaceId] },
  );

  // Fetch workspace settings
  const {
    data: settingsData,
    loading: settingsLoading,
    refetch: refetchSettings,
  } = useAuthenticatedFetch<{ settings: WorkspaceSettings }>(
    `/api/v1/workspaces/${workspaceId}/settings`,
    {
      defaultData: {
        settings: {
          name: organization?.name || 'My Workspace',
          description: '',
          default_role: 'member',
          allow_self_signup: false,
          max_members: 25,
          require_mfa: false,
          debate_approval_required: false,
        },
      },
      deps: [workspaceId],
    },
  );

  // Fetch recent activity
  const { data: activityData, loading: activityLoading } = useAuthenticatedFetch<{
    events: ActivityEvent[];
  }>(`/api/v1/workspaces/${workspaceId}/activity?limit=50`, {
    defaultData: { events: [] },
    deps: [workspaceId],
  });

  // Fetch pending invites
  const {
    data: invitesData,
    loading: invitesLoading,
    refetch: refetchInvites,
  } = useAuthenticatedFetch<{ invites: PendingInvite[] }>(
    `/api/v1/workspaces/${workspaceId}/invites`,
    { defaultData: { invites: [] }, deps: [workspaceId] },
  );

  // =========================================================================
  // Transform API data to component props
  // =========================================================================

  const members: WorkspaceMember[] = useMemo(() => {
    if (!membersData?.members) return [];
    return membersData.members.map((m) => ({
      id: m.id,
      name: m.name || m.email?.split('@')[0] || 'Unknown',
      email: m.email || `${m.user_id}@workspace`,
      role: m.role,
      status: m.status,
      joinedAt: m.joined_at,
      workspaceId,
      permissions: m.permissions,
    }));
  }, [membersData, workspaceId]);

  const workspaceRoles: WorkspaceRole[] = useMemo(() => {
    if (!rolesData?.roles) return [];
    return rolesData.roles.map((r) => ({
      id: r.id,
      name: r.name,
      description: r.description,
      permissions: r.permissions,
      isDefault: r.is_default || false,
    }));
  }, [rolesData]);

  const matrixRoles: Role[] = useMemo(() => {
    if (!rolesData?.roles) return [];
    return rolesData.roles.map((r) => ({
      id: r.id,
      name: r.name,
      description: r.description,
      permissions: r.permissions,
      isBuiltin: r.is_builtin || false,
      parentRole: r.parent_role,
    }));
  }, [rolesData]);

  const permissions: Permission[] = useMemo(() => {
    if (!permissionsData?.permissions) return [];
    return permissionsData.permissions.map((p) => ({
      id: p.id,
      resource: p.resource,
      action: p.action,
      description: p.description,
    }));
  }, [permissionsData]);

  const costItems: CostItem[] = useMemo(() => {
    if (!costData?.items) return [];
    return costData.items.map((c) => ({
      id: c.id,
      label: c.label,
      cost: c.cost,
      category: c.category,
      subcategory: c.subcategory,
    }));
  }, [costData]);

  // =========================================================================
  // Member actions (use real API calls)
  // =========================================================================

  const handleRoleChange = async (memberId: string, newRole: string) => {
    try {
      await authFetch(`/api/v1/workspaces/${workspaceId}/members/${memberId}/role`, {
        method: 'PUT',
        body: JSON.stringify({ role: newRole }),
      });
      await refetchMembers();
    } catch (error) {
      console.error('Failed to change role:', error);
    }
  };

  const handleInvite = async (email: string, role: string) => {
    try {
      await authFetch(`/api/v1/workspaces/${workspaceId}/invites`, {
        method: 'POST',
        body: JSON.stringify({ email, role }),
      });
      await refetchMembers();
    } catch (error) {
      console.error('Failed to invite member:', error);
    }
  };

  const handleRemove = async (memberId: string) => {
    try {
      await authFetch(`/api/v1/workspaces/${workspaceId}/members/${memberId}`, {
        method: 'DELETE',
      });
      await refetchMembers();
    } catch (error) {
      console.error('Failed to remove member:', error);
    }
  };

  const handleBulkAction = async (action: string, memberIds: string[]) => {
    try {
      await authFetch(`/api/v1/workspaces/${workspaceId}/members/bulk`, {
        method: 'POST',
        body: JSON.stringify({ action, member_ids: memberIds }),
      });
      await refetchMembers();
    } catch (error) {
      console.error('Failed to perform bulk action:', error);
    }
  };

  // =========================================================================
  // Settings actions
  // =========================================================================

  const handleEditSettings = useCallback(() => {
    setSettingsForm(settingsData?.settings || null);
    setEditing(true);
    setSaveSuccess(false);
  }, [settingsData]);

  const handleSaveSettings = useCallback(async () => {
    if (!settingsForm) return;
    setSaving(true);
    setSaveSuccess(false);
    try {
      await authFetch(`/api/v1/workspaces/${workspaceId}/settings`, {
        method: 'PUT',
        body: JSON.stringify(settingsForm),
      });
      await refetchSettings();
      setEditing(false);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (error) {
      console.error('Failed to save settings:', error);
    } finally {
      setSaving(false);
    }
  }, [settingsForm, authFetch, workspaceId, refetchSettings]);

  const handleRevokeInvite = useCallback(
    async (inviteId: string) => {
      try {
        await authFetch(`/api/v1/workspaces/${workspaceId}/invites/${inviteId}`, {
          method: 'DELETE',
        });
        await refetchInvites();
      } catch (error) {
        console.error('Failed to revoke invite:', error);
      }
    },
    [authFetch, workspaceId, refetchInvites],
  );

  const handleResendInvite = useCallback(
    async (inviteId: string) => {
      try {
        await authFetch(`/api/v1/workspaces/${workspaceId}/invites/${inviteId}/resend`, {
          method: 'POST',
        });
      } catch (error) {
        console.error('Failed to resend invite:', error);
      }
    },
    [authFetch, workspaceId],
  );

  // =========================================================================
  // Loading states
  // =========================================================================

  const loading =
    activeTab === 'members'
      ? membersLoading || invitesLoading
      : activeTab === 'roles'
        ? rolesLoading || permissionsLoading
        : activeTab === 'costs'
          ? costLoading
          : activeTab === 'settings'
            ? settingsLoading
            : activityLoading;

  const error = membersError || rolesError;

  const pendingInvites = invitesData?.invites || [];
  const activityEvents = activityData?.events || [];
  const settings = settingsData?.settings;

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'members', label: 'MEMBERS', count: members.length },
    { id: 'roles', label: 'ROLES' },
    { id: 'costs', label: 'COSTS' },
    { id: 'settings', label: 'SETTINGS' },
    { id: 'activity', label: 'ACTIVITY' },
  ];

  return (
    <AdminLayout title="Workspace Management">
      {/* Error Banner */}
      {error && (
        <div className="mb-4 p-3 border border-red-500/30 bg-red-500/10 text-red-400 text-sm font-theme-data">
          {error}
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 mb-6 border-b border-[var(--accent)]/20">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-3 font-theme-data text-sm transition-colors relative ${
              activeTab === tab.id ? 'text-[var(--accent)]' : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.label}
            {tab.count !== undefined && tab.count > 0 && (
              <span className="ml-1.5 text-xs text-text-muted">{tab.count}</span>
            )}
            {activeTab === tab.id && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--accent)]" />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'members' && (
        <>
          {/* Pending Invites */}
          {pendingInvites.length > 0 && (
            <div className="mb-6">
              <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">
                PENDING INVITES ({pendingInvites.length})
              </h3>
              <div className="space-y-2">
                {pendingInvites.map((invite) => (
                  <div
                    key={invite.id}
                    className="flex items-center justify-between p-3 border border-[var(--acid-cyan)]/20 bg-surface/30"
                  >
                    <div className="flex-1">
                      <span className="font-theme-data text-sm text-text">{invite.email}</span>
                      <span className="ml-3 text-xs font-theme-data text-text-muted">
                        {invite.role}
                      </span>
                      <span className="ml-3 text-xs font-theme-data text-text-muted/60">
                        invited {new Date(invite.invited_at).toLocaleDateString()}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleResendInvite(invite.id)}
                        className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                      >
                        RESEND
                      </button>
                      <button
                        onClick={() => handleRevokeInvite(invite.id)}
                        className="px-3 py-1 text-xs font-theme-data border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors"
                      >
                        REVOKE
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {members.length === 0 && !loading && (
            <div className="p-8 text-center border border-[var(--accent)]/20 bg-surface/30">
              <p className="text-text-muted text-sm font-theme-data mb-2">No members found</p>
              <p className="text-text-muted/60 text-xs font-theme-data">
                Invite team members to collaborate on debates and decisions.
              </p>
            </div>
          )}
          {(members.length > 0 || loading) && (
            <WorkspaceMemberManager
              workspaceId={workspaceId}
              members={members}
              roles={workspaceRoles}
              loading={loading}
              onRoleChange={handleRoleChange}
              onInvite={handleInvite}
              onRemove={handleRemove}
              onBulkAction={handleBulkAction}
            />
          )}
        </>
      )}

      {activeTab === 'roles' && (
        <>
          {matrixRoles.length === 0 && !loading && (
            <div className="p-8 text-center border border-[var(--accent)]/20 bg-surface/30">
              <p className="text-text-muted text-sm font-theme-data mb-2">No roles configured</p>
              <p className="text-text-muted/60 text-xs font-theme-data">
                Role-based access control is not configured for this workspace.
              </p>
            </div>
          )}
          {(matrixRoles.length > 0 || loading) && (
            <RoleMatrixViewer
              roles={matrixRoles}
              permissions={permissions}
              loading={loading}
              groupByResource={true}
              onRoleClick={() => {}}
              onPermissionClick={() => {}}
            />
          )}
        </>
      )}

      {activeTab === 'costs' && (
        <>
          {costItems.length === 0 && !loading && (
            <div className="p-8 text-center border border-[var(--accent)]/20 bg-surface/30">
              <p className="text-text-muted text-sm font-theme-data mb-2">No cost data available</p>
              <p className="text-text-muted/60 text-xs font-theme-data">
                Cost tracking will appear once debates and workflows are executed.
              </p>
            </div>
          )}
          {(costItems.length > 0 || loading) && (
            <CostBreakdownChart
              data={costItems}
              title="WORKSPACE COST BREAKDOWN"
              breakdownType={breakdownType}
              onBreakdownTypeChange={setBreakdownType}
              onTimeRangeChange={setTimeRange}
              onItemClick={() => {}}
              loading={loading}
            />
          )}
        </>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && settings && (
        <div className="space-y-6">
          {saveSuccess && (
            <div className="p-3 border border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent)] text-sm font-theme-data">
              Settings saved successfully.
            </div>
          )}

          {/* Workspace Info */}
          <div className="border border-[var(--accent)]/20 p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-theme-data text-[var(--accent)]">WORKSPACE INFO</h3>
              {!editing ? (
                <button
                  onClick={handleEditSettings}
                  className="px-4 py-2 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                >
                  EDIT
                </button>
              ) : (
                <div className="flex gap-2">
                  <button
                    onClick={() => setEditing(false)}
                    className="px-4 py-2 text-xs font-theme-data border border-text-muted/30 text-text-muted hover:bg-surface transition-colors"
                  >
                    CANCEL
                  </button>
                  <button
                    onClick={handleSaveSettings}
                    disabled={saving}
                    className={`px-4 py-2 text-xs font-theme-data border transition-colors ${
                      saving
                        ? 'border-text-muted/30 text-text-muted cursor-wait'
                        : 'border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10'
                    }`}
                  >
                    {saving ? 'SAVING...' : 'SAVE'}
                  </button>
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">NAME</label>
                {editing ? (
                  <input
                    type="text"
                    value={settingsForm?.name || ''}
                    onChange={(e) =>
                      setSettingsForm((prev) => (prev ? { ...prev, name: e.target.value } : prev))
                    }
                    className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
                  />
                ) : (
                  <p className="font-theme-data text-sm text-text">{settings.name}</p>
                )}
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  DESCRIPTION
                </label>
                {editing ? (
                  <textarea
                    value={settingsForm?.description || ''}
                    onChange={(e) =>
                      setSettingsForm((prev) =>
                        prev ? { ...prev, description: e.target.value } : prev,
                      )
                    }
                    rows={3}
                    className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none resize-none"
                  />
                ) : (
                  <p className="font-theme-data text-sm text-text-muted">
                    {settings.description || 'No description set.'}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Access & Security */}
          <div className="border border-[var(--accent)]/20 p-6">
            <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">ACCESS & SECURITY</h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-theme-data text-sm text-text">Default role for new members</p>
                  <p className="text-xs font-theme-data text-text-muted">
                    Assigned when someone joins via invite
                  </p>
                </div>
                {editing ? (
                  <select
                    value={settingsForm?.default_role || 'member'}
                    onChange={(e) =>
                      setSettingsForm((prev) =>
                        prev ? { ...prev, default_role: e.target.value } : prev,
                      )
                    }
                    className="bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
                  >
                    {workspaceRoles.map((r) => (
                      <option key={r.id} value={r.name}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                    {settings.default_role}
                  </span>
                )}
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-theme-data text-sm text-text">Maximum members</p>
                  <p className="text-xs font-theme-data text-text-muted">
                    Limit on workspace membership
                  </p>
                </div>
                {editing ? (
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={settingsForm?.max_members || 25}
                    onChange={(e) =>
                      setSettingsForm((prev) =>
                        prev ? { ...prev, max_members: parseInt(e.target.value) || 25 } : prev,
                      )
                    }
                    className="w-20 bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text text-right focus:border-[var(--accent)] focus:outline-none"
                  />
                ) : (
                  <span className="font-theme-data text-sm text-text">{settings.max_members}</span>
                )}
              </div>

              <ToggleSetting
                label="Require MFA"
                description="All members must enable multi-factor authentication"
                checked={editing ? settingsForm?.require_mfa || false : settings.require_mfa}
                disabled={!editing}
                onChange={(v) =>
                  setSettingsForm((prev) => (prev ? { ...prev, require_mfa: v } : prev))
                }
              />

              <ToggleSetting
                label="Debate approval required"
                description="New debates require admin approval before starting"
                checked={
                  editing
                    ? settingsForm?.debate_approval_required || false
                    : settings.debate_approval_required
                }
                disabled={!editing}
                onChange={(v) =>
                  setSettingsForm((prev) =>
                    prev ? { ...prev, debate_approval_required: v } : prev,
                  )
                }
              />

              <ToggleSetting
                label="Allow self-signup"
                description="Anyone with the workspace URL can request to join"
                checked={
                  editing ? settingsForm?.allow_self_signup || false : settings.allow_self_signup
                }
                disabled={!editing}
                onChange={(v) =>
                  setSettingsForm((prev) => (prev ? { ...prev, allow_self_signup: v } : prev))
                }
              />
            </div>
          </div>

          {/* Workspace Stats */}
          <div className="border border-[var(--accent)]/20 p-6">
            <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
              WORKSPACE OVERVIEW
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard label="MEMBERS" value={members.length} />
              <StatCard label="PENDING" value={pendingInvites.length} />
              <StatCard label="ROLES" value={matrixRoles.length} />
              <StatCard label="COST (30D)" value={`$${(costData?.total || 0).toFixed(2)}`} />
            </div>
          </div>
        </div>
      )}

      {/* Activity Tab */}
      {activeTab === 'activity' && (
        <div>
          {activityEvents.length === 0 && !loading && (
            <div className="p-8 text-center border border-[var(--accent)]/20 bg-surface/30">
              <p className="text-text-muted text-sm font-theme-data mb-2">No recent activity</p>
              <p className="text-text-muted/60 text-xs font-theme-data">
                Activity will appear as members use the workspace.
              </p>
            </div>
          )}
          {activityEvents.length > 0 && (
            <div className="space-y-0">
              {activityEvents.map((event, i) => (
                <div
                  key={event.id}
                  className={`flex items-start gap-4 p-4 border-l-2 ${
                    i === 0 ? 'border-l-acid-green' : 'border-l-acid-green/20'
                  } ${i < activityEvents.length - 1 ? 'border-b border-b-surface' : ''}`}
                >
                  <div className="flex-shrink-0 w-8 h-8 flex items-center justify-center border border-[var(--accent)]/20 bg-surface/50 font-theme-data text-xs text-[var(--accent)]">
                    {event.type === 'member_joined'
                      ? '+'
                      : event.type === 'member_removed'
                        ? '-'
                        : event.type === 'debate_created'
                          ? 'D'
                          : event.type === 'debate_completed'
                            ? '>'
                            : event.type === 'role_changed'
                              ? 'R'
                              : event.type === 'settings_updated'
                                ? 'S'
                                : event.type === 'invite_sent'
                                  ? '@'
                                  : '?'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-theme-data text-sm text-text">{event.description}</p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-xs font-theme-data text-text-muted">{event.actor}</span>
                      <span className="text-xs font-theme-data text-text-muted/60">
                        {formatRelativeTime(event.timestamp)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </AdminLayout>
  );
}

// =============================================================================
// Helper Components
// =============================================================================

function ToggleSetting({
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="font-theme-data text-sm text-text">{label}</p>
        <p className="text-xs font-theme-data text-text-muted">{description}</p>
      </div>
      <button
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors ${
          checked ? 'bg-[var(--accent)]/60' : 'bg-surface'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-text transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-[var(--accent)]/20 p-4 bg-surface/30">
      <p className="text-xs font-theme-data text-text-muted mb-1">{label}</p>
      <p className="text-xl font-theme-data font-bold text-[var(--accent)]">{value}</p>
    </div>
  );
}

function formatRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diff = now - then;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString();
}
