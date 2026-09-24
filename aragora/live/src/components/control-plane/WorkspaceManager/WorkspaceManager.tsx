'use client';

import { useState, useCallback } from 'react';
import { WorkspaceSettings } from './WorkspaceSettings';
import { TeamAccessPanel } from './TeamAccessPanel';
import { useWorkspaces, type Workspace as HookWorkspace } from '@/hooks/useWorkspaces';

export interface WorkspaceMember {
  id: string;
  name: string;
  email: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  joinedAt: string;
  lastActive?: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  owner: string;
  members: WorkspaceMember[];
  createdAt: string;
  updatedAt: string;
  settings: {
    defaultVertical?: string;
    complianceFrameworks: string[];
    agentLimit: number;
    documentsQuota: number;
    documentsUsed: number;
  };
}

export interface WorkspaceManagerProps {
  currentWorkspaceId?: string;
  onWorkspaceSelect?: (workspace: Workspace) => void;
  onWorkspaceCreate?: (name: string, description: string) => void;
  onWorkspaceUpdate?: (workspace: Workspace) => void;
  className?: string;
}

// Map hook workspace to component workspace type
function mapToComponentWorkspace(ws: HookWorkspace): Workspace {
  return {
    id: ws.id,
    name: ws.name,
    description: ws.description,
    owner: ws.owner,
    members: ws.members.map((m) => ({
      id: m.id,
      name: m.name,
      email: m.email,
      role: m.role,
      joinedAt: m.joinedAt,
      lastActive: m.lastActive,
    })),
    createdAt: ws.createdAt,
    updatedAt: ws.updatedAt,
    settings: ws.settings,
  };
}

type ViewMode = 'list' | 'settings' | 'team';

export function WorkspaceManager({
  currentWorkspaceId,
  onWorkspaceSelect,
  onWorkspaceUpdate,
  className = '',
}: WorkspaceManagerProps) {
  // Use the workspaces hook
  const {
    workspaces: hookWorkspaces,
    selectedWorkspace: hookSelectedWorkspace,
    loading,
    error,
    selectWorkspace,
    createWorkspace,
    updateWorkspace,
    deleteWorkspace,
    addMember,
    removeMember,
  } = useWorkspaces({ autoLoad: true });

  // Map to component types
  const workspaces = hookWorkspaces.map(mapToComponentWorkspace);
  const selectedWorkspace = hookSelectedWorkspace
    ? mapToComponentWorkspace(hookSelectedWorkspace)
    : null;

  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  // Select workspace on initial load if currentWorkspaceId is provided
  useState(() => {
    if (currentWorkspaceId && !hookSelectedWorkspace) {
      selectWorkspace(currentWorkspaceId);
    }
  });

  const handleWorkspaceClick = useCallback(
    (workspace: Workspace) => {
      selectWorkspace(workspace.id);
      onWorkspaceSelect?.(workspace);
    },
    [selectWorkspace, onWorkspaceSelect],
  );

  const getUsagePercent = (used: number, quota: number) => {
    return Math.min(100, Math.round((used / quota) * 100));
  };

  const getUsageColor = (percent: number) => {
    if (percent >= 90) return 'bg-red-500';
    if (percent >= 70) return 'bg-yellow-500';
    return 'bg-[var(--accent)]';
  };

  const getVerticalIcon = (vertical?: string) => {
    const icons: Record<string, string> = {
      software: '&#x1F4BB;',
      legal: '&#x2696;',
      healthcare: '&#x1F3E5;',
      accounting: '&#x1F4CA;',
      research: '&#x1F52C;',
    };
    return vertical ? icons[vertical] || '' : '';
  };

  // Handle workspace creation
  const handleCreateWorkspace = useCallback(
    async (name: string, description: string) => {
      setIsCreating(true);
      try {
        const workspace = await createWorkspace({ name, description });
        if (workspace) {
          setShowCreateModal(false);
          selectWorkspace(workspace.id);
        }
      } finally {
        setIsCreating(false);
      }
    },
    [createWorkspace, selectWorkspace],
  );

  // Handle workspace update (from settings)
  const handleWorkspaceUpdate = useCallback(
    async (updated: Workspace) => {
      const result = await updateWorkspace(updated.id, {
        name: updated.name,
        description: updated.description,
        settings: updated.settings,
      });
      if (result) {
        onWorkspaceUpdate?.(updated);
      }
    },
    [updateWorkspace, onWorkspaceUpdate],
  );

  // Handle member add
  const handleMemberAdd = useCallback(
    async (email: string, role: WorkspaceMember['role']) => {
      if (!selectedWorkspace) return;
      // Convert role to permissions
      const permissions =
        role === 'admin'
          ? ['read', 'write', 'admin']
          : role === 'member'
            ? ['read', 'write']
            : ['read'];
      await addMember(selectedWorkspace.id, email, permissions);
    },
    [selectedWorkspace, addMember],
  );

  // Handle member remove
  const handleMemberRemove = useCallback(
    async (memberId: string) => {
      if (!selectedWorkspace) return;
      await removeMember(selectedWorkspace.id, memberId);
    },
    [selectedWorkspace, removeMember],
  );

  // Handle role change (remove and re-add with new permissions)
  const handleRoleChange = useCallback(
    async (memberId: string, role: WorkspaceMember['role']) => {
      if (!selectedWorkspace) return;
      // For simplicity, we'll need to remove and re-add - or this could be a separate endpoint
      const permissions =
        role === 'admin'
          ? ['read', 'write', 'admin']
          : role === 'member'
            ? ['read', 'write']
            : ['read'];
      await removeMember(selectedWorkspace.id, memberId);
      await addMember(selectedWorkspace.id, memberId, permissions);
    },
    [selectedWorkspace, removeMember, addMember],
  );

  // Handle workspace delete
  const handleDeleteWorkspace = useCallback(async () => {
    if (!selectedWorkspace) return;
    const confirmed = window.confirm(
      `Are you sure you want to delete "${selectedWorkspace.name}"? This action cannot be undone.`,
    );
    if (confirmed) {
      await deleteWorkspace(selectedWorkspace.id, true);
      setViewMode('list');
    }
  }, [selectedWorkspace, deleteWorkspace]);

  return (
    <div className={`bg-surface border border-border rounded-lg overflow-hidden ${className}`}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-bg flex items-center justify-between">
        <div>
          <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">
            WORKSPACE MANAGER
          </h3>
          <p className="text-xs text-text-muted mt-1">
            {loading
              ? 'Loading...'
              : error
                ? `Error: ${error}`
                : 'Manage workspaces and team access'}
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          disabled={loading}
          className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
        >
          + NEW WORKSPACE
        </button>
      </div>

      {/* View Mode Tabs */}
      <div className="flex border-b border-border">
        {(['list', 'settings', 'team'] as ViewMode[]).map((mode) => (
          <button
            key={mode}
            onClick={() => setViewMode(mode)}
            disabled={mode !== 'list' && !selectedWorkspace}
            className={`
              px-4 py-2 text-xs font-theme-data uppercase transition-colors
              ${viewMode === mode ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-bg' : 'text-text-muted hover:text-text'}
              ${mode !== 'list' && !selectedWorkspace ? 'opacity-50 cursor-not-allowed' : ''}
            `}
          >
            {mode === 'list' ? 'Workspaces' : mode === 'settings' ? 'Settings' : 'Team'}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {loading && workspaces.length === 0 && (
          <div className="text-center py-8 text-text-muted font-theme-data">
            Loading workspaces...
          </div>
        )}

        {!loading && error && (
          <div className="text-center py-8 text-red-400 font-theme-data">Error: {error}</div>
        )}

        {!loading && !error && workspaces.length === 0 && (
          <div className="text-center py-8">
            <p className="text-text-muted font-theme-data mb-4">No workspaces found</p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
            >
              Create your first workspace
            </button>
          </div>
        )}

        {viewMode === 'list' && workspaces.length > 0 && (
          <div className="space-y-3">
            {workspaces.map((workspace) => {
              const usagePercent = getUsagePercent(
                workspace.settings.documentsUsed,
                workspace.settings.documentsQuota,
              );
              const isSelected = workspace.id === selectedWorkspace?.id;

              return (
                <div
                  key={workspace.id}
                  onClick={() => handleWorkspaceClick(workspace)}
                  className={`
                    p-4 rounded-lg border-2 cursor-pointer transition-all
                    ${isSelected ? 'border-[var(--accent)] bg-[var(--accent)]/5' : 'border-border hover:border-text-muted bg-bg'}
                  `}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <span
                        className="text-2xl"
                        dangerouslySetInnerHTML={{
                          __html:
                            getVerticalIcon(workspace.settings.defaultVertical) || '&#x1F4C1;',
                        }}
                      />
                      <div>
                        <h4 className="font-theme-data font-bold text-text">{workspace.name}</h4>
                        <p className="text-xs text-text-muted">{workspace.description}</p>
                      </div>
                    </div>
                    {isSelected && (
                      <span className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                        ACTIVE
                      </span>
                    )}
                  </div>

                  {/* Stats Row */}
                  <div className="flex items-center gap-6 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="text-text-muted">Members:</span>
                      <span className="font-theme-data text-text">{workspace.members.length}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-text-muted">Agents:</span>
                      <span className="font-theme-data text-text">
                        {workspace.settings.agentLimit}
                      </span>
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-text-muted">Documents:</span>
                        <span className="font-theme-data text-text">
                          {workspace.settings.documentsUsed.toLocaleString()} /{' '}
                          {workspace.settings.documentsQuota.toLocaleString()}
                        </span>
                      </div>
                      <div className="h-1.5 bg-surface rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all ${getUsageColor(usagePercent)}`}
                          style={{ width: `${usagePercent}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Compliance Frameworks */}
                  {workspace.settings.complianceFrameworks.length > 0 && (
                    <div className="flex items-center gap-1 mt-3">
                      {workspace.settings.complianceFrameworks.map((fw) => (
                        <span
                          key={fw}
                          className="px-1.5 py-0.5 text-xs font-theme-data bg-surface border border-border rounded"
                        >
                          {fw}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {viewMode === 'settings' && selectedWorkspace && (
          <WorkspaceSettings
            workspace={selectedWorkspace}
            onSave={handleWorkspaceUpdate}
            onDelete={handleDeleteWorkspace}
          />
        )}

        {viewMode === 'team' && selectedWorkspace && (
          <TeamAccessPanel
            workspace={selectedWorkspace}
            onMemberAdd={handleMemberAdd}
            onMemberRemove={handleMemberRemove}
            onRoleChange={handleRoleChange}
          />
        )}
      </div>

      {/* Create Workspace Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-bg/80 flex items-center justify-center z-50">
          <div className="bg-surface border border-border rounded-lg p-6 w-full max-w-md">
            <h3 className="font-theme-data font-bold text-[var(--accent)] mb-4">
              CREATE WORKSPACE
            </h3>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const form = e.target as HTMLFormElement;
                const name = (form.elements.namedItem('name') as HTMLInputElement).value;
                const description = (form.elements.namedItem('description') as HTMLTextAreaElement)
                  .value;
                await handleCreateWorkspace(name, description);
              }}
            >
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-1">NAME</label>
                  <input
                    name="name"
                    type="text"
                    required
                    disabled={isCreating}
                    className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] disabled:opacity-50"
                    placeholder="Workspace name"
                  />
                </div>
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-1">
                    DESCRIPTION
                  </label>
                  <textarea
                    name="description"
                    rows={3}
                    disabled={isCreating}
                    className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] resize-none disabled:opacity-50"
                    placeholder="Workspace description"
                  />
                </div>
              </div>
              <div className="flex gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  disabled={isCreating}
                  className="flex-1 px-4 py-2 text-xs font-theme-data border border-border rounded hover:border-text-muted transition-colors disabled:opacity-50"
                >
                  CANCEL
                </button>
                <button
                  type="submit"
                  disabled={isCreating}
                  className="flex-1 px-4 py-2 text-xs font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
                >
                  {isCreating ? 'CREATING...' : 'CREATE'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
