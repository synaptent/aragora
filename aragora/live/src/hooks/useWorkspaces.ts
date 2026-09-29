'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export interface WorkspaceMember {
  id: string;
  name: string;
  email: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  permissions: string[];
  joinedAt: string;
  lastActive?: string;
}

export interface WorkspaceSettings {
  defaultVertical?: string;
  complianceFrameworks: string[];
  agentLimit: number;
  documentsQuota: number;
  documentsUsed: number;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  owner: string;
  organization_id: string;
  members: WorkspaceMember[];
  createdAt: string;
  updatedAt: string;
  settings: WorkspaceSettings;
}

export interface CreateWorkspaceData {
  name: string;
  description?: string;
  organization_id?: string;
  members?: string[];
}

export interface UpdateWorkspaceData {
  name?: string;
  description?: string;
  settings?: Partial<WorkspaceSettings>;
}

export interface AddMemberData {
  user_id: string;
  permissions?: string[];
}

interface UseWorkspacesState {
  workspaces: Workspace[];
  loading: boolean;
  error: string | null;
}

// ============================================================================
// Hook
// ============================================================================

export interface UseWorkspacesOptions {
  /** Organization ID to filter workspaces */
  organizationId?: string;
  /** Auto-load on mount */
  autoLoad?: boolean;
}

export interface UseWorkspacesReturn extends UseWorkspacesState {
  // Selected workspace
  selectedWorkspace: Workspace | null;
  selectWorkspace: (id: string | null) => void;

  // Load methods
  loadWorkspaces: (organizationId?: string) => Promise<void>;
  loadWorkspace: (id: string) => Promise<Workspace | null>;
  refetch: () => Promise<void>;

  // Workspace CRUD
  createWorkspace: (data: CreateWorkspaceData) => Promise<Workspace | null>;
  updateWorkspace: (id: string, data: UpdateWorkspaceData) => Promise<Workspace | null>;
  deleteWorkspace: (id: string, force?: boolean) => Promise<boolean>;

  // Member management
  addMember: (workspaceId: string, userId: string, permissions?: string[]) => Promise<boolean>;
  removeMember: (workspaceId: string, userId: string) => Promise<boolean>;
}

/**
 * Hook for managing workspaces and team members.
 *
 * @example
 * ```tsx
 * const {
 *   workspaces,
 *   selectedWorkspace,
 *   loading,
 *   createWorkspace,
 *   addMember,
 *   removeMember,
 * } = useWorkspaces({ autoLoad: true });
 *
 * // Create a new workspace
 * const ws = await createWorkspace({ name: 'Engineering', description: 'Dev team' });
 *
 * // Add a member
 * await addMember(ws.id, 'user_123', ['read', 'write']);
 * ```
 */
export function useWorkspaces(options: UseWorkspacesOptions = {}): UseWorkspacesReturn {
  const { organizationId, autoLoad = true } = options;

  const [state, setState] = useState<UseWorkspacesState>({
    workspaces: [],
    loading: true,
    error: null,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // =========================================================================
  // Load methods
  // =========================================================================

  const loadWorkspaces = useCallback(
    async (orgId?: string) => {
      setState((s) => ({ ...s, loading: true, error: null }));

      try {
        const params = new URLSearchParams();
        const filterOrgId = orgId || organizationId;
        if (filterOrgId) params.set('organization_id', filterOrgId);

        const query = params.toString();
        const url = `${API_BASE}/api/workspaces${query ? `?${query}` : ''}`;

        const response = await fetch(url);
        if (!response.ok) {
          if (response.status === 401) {
            throw new Error('Not authenticated');
          }
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const workspaces = (data.workspaces || []).map(mapBackendWorkspace);

        setState((s) => ({ ...s, workspaces, loading: false }));

        // Auto-select first workspace if none selected
        if (workspaces.length > 0 && !selectedId) {
          setSelectedId(workspaces[0].id);
        }
      } catch (e) {
        setState((s) => ({
          ...s,
          loading: false,
          error: e instanceof Error ? e.message : 'Failed to load workspaces',
        }));
      }
    },
    [organizationId, selectedId],
  );

  const loadWorkspace = useCallback(async (id: string): Promise<Workspace | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/workspaces/${id}`);
      if (!response.ok) {
        if (response.status === 404) return null;
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      return mapBackendWorkspace(data.workspace);
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : 'Failed to load workspace',
      }));
      return null;
    }
  }, []);

  const refetch = useCallback(async () => {
    await loadWorkspaces();
  }, [loadWorkspaces]);

  // =========================================================================
  // Workspace CRUD
  // =========================================================================

  const createWorkspace = useCallback(
    async (data: CreateWorkspaceData): Promise<Workspace | null> => {
      try {
        const response = await fetch(`${API_BASE}/api/workspaces`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        const result = await response.json();
        const workspace = mapBackendWorkspace(result.workspace);

        // Update local state
        setState((s) => ({ ...s, workspaces: [...s.workspaces, workspace] }));

        return workspace;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to create workspace',
        }));
        return null;
      }
    },
    [],
  );

  const updateWorkspace = useCallback(
    async (id: string, data: UpdateWorkspaceData): Promise<Workspace | null> => {
      try {
        // Note: Backend uses PUT for updates on retention policies
        // Workspaces may need PATCH - adjust based on actual API behavior
        const response = await fetch(`${API_BASE}/api/workspaces/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        const result = await response.json();
        const workspace = mapBackendWorkspace(result.workspace);

        // Update local state
        setState((s) => ({
          ...s,
          workspaces: s.workspaces.map((w) => (w.id === id ? workspace : w)),
        }));

        return workspace;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to update workspace',
        }));
        return null;
      }
    },
    [],
  );

  const deleteWorkspace = useCallback(
    async (id: string, force = false): Promise<boolean> => {
      try {
        const response = await fetch(`${API_BASE}/api/workspaces/${id}`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force }),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        // Update local state
        setState((s) => ({ ...s, workspaces: s.workspaces.filter((w) => w.id !== id) }));

        // Clear selection if deleted
        if (selectedId === id) {
          setSelectedId(null);
        }

        return true;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to delete workspace',
        }));
        return false;
      }
    },
    [selectedId],
  );

  // =========================================================================
  // Member management
  // =========================================================================

  const addMember = useCallback(
    async (
      workspaceId: string,
      userId: string,
      permissions: string[] = ['read'],
    ): Promise<boolean> => {
      try {
        const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/members`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, permissions }),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        // Refetch workspace to get updated members
        const updated = await loadWorkspace(workspaceId);
        if (updated) {
          setState((s) => ({
            ...s,
            workspaces: s.workspaces.map((w) => (w.id === workspaceId ? updated : w)),
          }));
        }

        return true;
      } catch (e) {
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Failed to add member' }));
        return false;
      }
    },
    [loadWorkspace],
  );

  const removeMember = useCallback(
    async (workspaceId: string, userId: string): Promise<boolean> => {
      try {
        const response = await fetch(
          `${API_BASE}/api/workspaces/${workspaceId}/members/${userId}`,
          { method: 'DELETE' },
        );

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        // Update local state - remove member from workspace
        setState((s) => ({
          ...s,
          workspaces: s.workspaces.map((w) => {
            if (w.id !== workspaceId) return w;
            return { ...w, members: w.members.filter((m) => m.id !== userId) };
          }),
        }));

        return true;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to remove member',
        }));
        return false;
      }
    },
    [],
  );

  // =========================================================================
  // Selection
  // =========================================================================

  const selectWorkspace = useCallback((id: string | null) => {
    setSelectedId(id);
  }, []);

  const selectedWorkspace = useMemo(() => {
    return state.workspaces.find((w) => w.id === selectedId) || null;
  }, [state.workspaces, selectedId]);

  // =========================================================================
  // Auto-load
  // =========================================================================

  useEffect(() => {
    if (autoLoad) {
      loadWorkspaces();
    }
  }, [autoLoad, loadWorkspaces]);

  return {
    ...state,
    selectedWorkspace,
    selectWorkspace,
    loadWorkspaces,
    loadWorkspace,
    refetch,
    createWorkspace,
    updateWorkspace,
    deleteWorkspace,
    addMember,
    removeMember,
  };
}

// ============================================================================
// Helpers
// ============================================================================

/**
 * Map backend workspace response to frontend Workspace type.
 * The backend DataIsolationManager returns a different structure.
 */
function mapBackendWorkspace(data: Record<string, unknown>): Workspace {
  // Backend workspace structure from DataIsolationManager.to_dict():
  // { id, name, organization_id, created_by, created_at, encryption_key_id, members: {...} }

  const members: WorkspaceMember[] = [];

  // Backend members is a dict: { user_id: { permissions: [...], added_at, added_by } }
  if (data.members && typeof data.members === 'object') {
    const membersDict = data.members as Record<
      string,
      { permissions?: string[]; added_at?: string; added_by?: string }
    >;
    for (const [userId, memberData] of Object.entries(membersDict)) {
      const perms = memberData.permissions || [];
      // Determine role from permissions
      let role: WorkspaceMember['role'] = 'viewer';
      if (userId === data.created_by) {
        role = 'owner';
      } else if (perms.includes('admin') || perms.includes('manage')) {
        role = 'admin';
      } else if (perms.includes('write')) {
        role = 'member';
      }

      members.push({
        id: userId,
        name: userId, // Backend doesn't include name - would need user lookup
        email: `${userId}@workspace`, // Placeholder
        role,
        permissions: perms,
        joinedAt: memberData.added_at || new Date().toISOString(),
        lastActive: undefined,
      });
    }
  }

  return {
    id: (data.id as string) || '',
    name: (data.name as string) || '',
    description: (data.description as string) || '',
    owner: (data.created_by as string) || '',
    organization_id: (data.organization_id as string) || '',
    members,
    createdAt: (data.created_at as string) || new Date().toISOString(),
    updatedAt:
      (data.updated_at as string) || (data.created_at as string) || new Date().toISOString(),
    settings: {
      defaultVertical: (data.default_vertical as string) || undefined,
      complianceFrameworks: (data.compliance_frameworks as string[]) || [],
      agentLimit: (data.agent_limit as number) || 10,
      documentsQuota: (data.documents_quota as number) || 10000,
      documentsUsed: (data.documents_used as number) || 0,
    },
  };
}

export default useWorkspaces;
